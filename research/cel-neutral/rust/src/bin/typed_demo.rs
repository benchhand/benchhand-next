//! The typed demo on the Rust engines.
//!
//! cel-core 0.5.1: env YAML (through the adapter in lib.rs) plus the generated FileDescriptorSet, checked
//! at compile; it also evaluates the CheckedExprs the other engines wrote and writes its own.
//! cel 0.16.1: no checker, so the reject cases are run to show they only fail, if at all, at evaluation.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context as _, Result};
use cel_core::{Ast, Env, MapActivation, Value};
use cel_core_proto::{AstToProto, CheckedExpr, ParsedExpr, ProstMessage, check_result_from_proto, from_parsed_expr};
use cel_neutral_rs::{EnvConfig, env_from_config};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};
use serde::Deserialize;

#[derive(Deserialize)]
struct Rule {
    expr: String,
    #[serde(default)]
    expect: Option<bool>,
    #[serde(default)]
    why: String,
}

#[derive(Deserialize)]
struct Demo {
    scope: String,
    accept: Vec<Rule>,
    reject: Vec<Rule>,
}

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn activation(pool: &DescriptorPool, config: &EnvConfig, json: &serde_json::Value) -> Result<MapActivation> {
    let mut act = MapActivation::new();
    for var in &config.variables {
        let desc = pool.get_message_by_name(&var.type_name).context("message type")?;
        let value = json[&var.name].to_string();
        let mut de = serde_json::Deserializer::from_str(&value);
        // Omitted (non-structural) fields aren't declared, so the binding drops them.
        let options = prost_reflect::DeserializeOptions::new().deny_unknown_fields(false);
        let msg = DynamicMessage::deserialize_with_options(desc, &mut de, &options)?;
        act.insert(var.name.clone(), Value::Message(Box::new(ProstMessage::new(msg))));
    }
    Ok(act)
}

/// The shipped form: a google.protobuf.Any holding a cel.expr.CheckedExpr, as cel-cpp writes it.
fn wrap_any(checked: &CheckedExpr) -> Vec<u8> {
    prost_types::Any { type_url: "type.googleapis.com/cel.expr.CheckedExpr".into(), value: checked.encode_to_vec() }
        .encode_to_vec()
}

fn unwrap_any(bytes: &[u8]) -> Result<CheckedExpr> {
    let any = prost_types::Any::decode(bytes)?;
    Ok(CheckedExpr::decode(any.value.as_slice())?)
}

/// Evaluate a CheckedExpr another engine wrote, without parsing or checking it here.
fn eval_shipped(env: &Env, act: &MapActivation, checked: &CheckedExpr) -> Result<Value> {
    let parsed = ParsedExpr { expr: checked.expr.clone(), source_info: checked.source_info.clone() };
    let expr = from_parsed_expr(&parsed)?;
    let ast = Ast::new_checked(expr, "", check_result_from_proto(checked)?);
    Ok(env.program(&ast)?.eval(act))
}

fn cel_core_demo(demo: &Demo, config: &EnvConfig, fds: &[u8], json: &serde_json::Value) -> Result<usize> {
    let env = env_from_config(config, fds)?;
    let pool = DescriptorPool::decode(fds)?;
    let act = activation(&pool, config, json)?;
    let mut failures = 0;
    let out = root().join("generated/checked/rust-cel-core");
    fs::create_dir_all(&out)?;
    for (i, rule) in demo.accept.iter().enumerate() {
        match env.compile(&rule.expr) {
            Ok(ast) => {
                let got = env.program(&ast)?.eval(&act);
                let ok = got == Value::Bool(rule.expect.unwrap_or(true));
                failures += usize::from(!ok);
                println!("{} accept {:?} -> {got}", if ok { "ok " } else { "BAD" }, rule.expr);
                fs::write(out.join(format!("accept-{i}.binpb")), wrap_any(&ast.to_checked_expr()?))?;
            }
            Err(e) => {
                failures += 1;
                println!("BAD accept {:?}: {}", rule.expr, e.to_string().lines().next().unwrap_or(""));
            }
        }
    }
    for rule in &demo.reject {
        match env.compile(&rule.expr) {
            Err(e) => println!("ok  reject {:?}: {}", rule.expr, e.to_string().lines().next().unwrap_or("")),
            Ok(_) => {
                failures += 1;
                println!("BAD reject {:?} type-checked; expected: {}", rule.expr, rule.why);
            }
        }
    }
    failures += shipped(&env, &act, demo)?;
    println!("cel-core: {failures} failures");
    Ok(failures)
}

fn shipped(env: &Env, act: &MapActivation, demo: &Demo) -> Result<usize> {
    let mut failures = 0;
    let mut dirs: Vec<_> = fs::read_dir(root().join("generated/checked"))?.flatten().map(|e| e.path()).collect();
    dirs.sort();
    for dir in dirs.iter().filter(|d| !d.ends_with("rust-cel-core")) {
        for (i, rule) in demo.accept.iter().enumerate() {
            let name = dir.file_name().unwrap().to_string_lossy();
            let got = unwrap_any(&fs::read(dir.join(format!("accept-{i}.binpb")))?)
                .and_then(|checked| eval_shipped(env, act, &checked));
            let ok = matches!(&got, Ok(v) if *v == Value::Bool(rule.expect.unwrap_or(true)));
            failures += usize::from(!ok);
            println!("{} shipped from {name} accept-{i} -> {got:?}", if ok { "ok " } else { "BAD" });
        }
    }
    Ok(failures)
}

/// cel 0.16.1 parses only; there is no type check to fail, so reject cases reach evaluation.
fn cel_rust_demo(demo: &Demo, json: &serde_json::Value) -> Result<()> {
    let env = Arc::new(cel::Env::stdlib());
    let mut ctx = cel::Context::with_env(env.clone());
    let vars: HashMap<String, serde_json::Value> = serde_json::from_value(json.clone())?;
    for (name, value) in vars {
        ctx.add_variable(name, value)?;
    }
    for rule in demo.accept.iter().chain(demo.reject.iter()) {
        let compiled = env.compile(&rule.expr);
        let result = compiled.map(|p| p.execute(&ctx));
        println!("cel 0.16.1 {:?}: compiles={} -> {:?}", rule.expr, result.is_ok(), result.map_err(|e| e.to_string()));
    }
    Ok(())
}

fn main() -> Result<()> {
    let root = root();
    let demo: Demo = serde_yaml::from_str(&fs::read_to_string(root.join("typedemo/gate_guard.yaml"))?)?;
    let generated = root.join("generated");
    let env_yaml = fs::read_to_string(generated.join(format!("env/{}.env.yaml", demo.scope)))?;
    let config: EnvConfig = serde_yaml::from_str(&env_yaml)?;
    let fds = fs::read(generated.join("types.binpb"))?;
    let json: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(generated.join(format!("activation/{}.json", demo.scope)))?)?;
    let failures = cel_core_demo(&demo, &config, &fds, &json)?;
    cel_rust_demo(&demo, &json)?;
    std::process::exit(i32::from(failures > 0));
}
