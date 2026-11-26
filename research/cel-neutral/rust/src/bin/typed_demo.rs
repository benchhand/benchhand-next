//! The typed demo on the Rust engines.
//!
//! cel-core 0.5.1: the environment comes from the gate_guard profile manifest (lib.rs), checked at
//! compile. It writes its CheckedExprs with a bundle.json, evaluates the bundles the other engines wrote
//! after checking their profile and sources, runs the profile cases, and writes every outcome to
//! results/typed-demo/cel-core.json. cel-core is a candidate evaluator, not a checker of record: its own
//! check results are recorded for comparison.
//! cel 0.16.1: no checker, so the reject cases are run to show they only fail, if at all, at evaluation.

use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context as _, Result};
use cel_core::{Ast, Env, MapActivation, Value};
use cel_core_proto::{AstToProto, CheckedExpr, ParsedExpr, ProstMessage, check_result_from_proto, from_parsed_expr};
use cel_neutral_rs::{Profile, Record, env_from_profile, load_profile, write_results};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};
use serde::Deserialize;

const ENGINE: &str = "cel-core";

#[derive(Deserialize)]
struct Rule {
    expr: String,
    #[serde(default)]
    expect: Option<bool>,
    #[serde(default)]
    why: String,
    #[serde(default)]
    feature: String,
    #[serde(default)]
    refuse: bool,
    #[serde(default)]
    meaning: String,
    #[serde(default)]
    error: bool,
}

#[derive(Deserialize)]
struct Demo {
    scope: String,
    accept: Vec<Rule>,
    reject: Vec<Rule>,
    profile: Vec<Rule>,
    presence: Vec<Rule>,
}

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn activation(pool: &DescriptorPool, profile: &Profile, json: &serde_json::Value) -> Result<MapActivation> {
    let mut act = MapActivation::new();
    for var in &profile.manifest.variables {
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

fn first_line(e: impl std::fmt::Display) -> String {
    e.to_string().lines().next().unwrap_or("").to_string()
}

struct Run {
    env: Env,
    act: MapActivation,
    records: Vec<Record>,
}

impl Run {
    fn record(&mut self, kind: &str, case: &str, outcome: (bool, String), writer: Option<&str>) {
        let (ok, detail) = outcome;
        let from = writer.map(|w| format!(" from {w}")).unwrap_or_default();
        println!("{} {kind}{from} {case:?}: {detail}", if ok { "ok " } else { "BAD" });
        self.records.push(Record {
            engine: ENGINE.into(),
            kind: kind.into(),
            case: case.into(),
            writer: writer.map(str::to_string),
            ok,
            detail,
        });
    }

    fn eval_expr(&self, expr: &str) -> Result<Value> {
        let ast = self.env.compile(expr).map_err(|e| anyhow::anyhow!(first_line(e)))?;
        Ok(self.env.program(&ast)?.eval(&self.act))
    }

    /// Accept, reject and profile cases; returns the sources of the CheckedExprs written.
    fn cases(&mut self, demo: &Demo, out: &Path) -> Result<BTreeMap<String, String>> {
        let mut sources = BTreeMap::new();
        for (i, rule) in demo.accept.iter().enumerate() {
            let want = Value::Bool(rule.expect.unwrap_or(true));
            match self.env.compile(&rule.expr) {
                Ok(ast) => {
                    let got = self.env.program(&ast)?.eval(&self.act);
                    self.record("accept", &rule.expr, (got == want, format!("{got}")), None);
                    let name = format!("accept-{i}.binpb");
                    fs::write(out.join(&name), wrap_any(&ast.to_checked_expr()?))?;
                    sources.insert(name, rule.expr.clone());
                }
                Err(e) => self.record("accept", &rule.expr, (false, first_line(e)), None),
            }
        }
        for rule in &demo.reject {
            let outcome = match self.env.compile(&rule.expr) {
                Err(e) => (true, first_line(e)),
                Ok(_) => (false, format!("type-checked; expected: {}", rule.why)),
            };
            self.record("reject", &rule.expr, outcome, None);
        }
        for rule in &demo.profile {
            let got = self.eval_expr(&rule.expr);
            let outcome = match (rule.refuse, got) {
                (true, Err(e)) => (true, format!("{}: {e}", rule.feature)),
                (true, Ok(v)) => (false, format!("{}: checked, should be refused; evaluated to {v}", rule.feature)),
                (false, Ok(v)) => (v == Value::Bool(rule.expect.unwrap_or(true)), format!("{}: {v}", rule.feature)),
                (false, Err(e)) => (false, format!("{}: {e}", rule.feature)),
            };
            self.record("profile", &rule.expr, outcome, None);
        }
        for rule in &demo.presence {
            let outcome = match (rule.error, self.eval_expr(&rule.expr)) {
                (_, Err(e)) => (false, format!("{}: {e}", rule.meaning)),
                (true, Ok(v)) => (matches!(v, Value::Error(_)), format!("{}: {v:?}", rule.meaning)),
                (false, Ok(v)) => (v == Value::Bool(rule.expect.unwrap_or(true)), format!("{}: {v:?}", rule.meaning)),
            };
            self.record("presence", &rule.expr, outcome, None);
        }
        Ok(sources)
    }

    fn shipped(&mut self, profile: &Profile, demo: &Demo) -> Result<()> {
        let sources: BTreeMap<_, _> =
            demo.accept.iter().enumerate().map(|(i, r)| (format!("accept-{i}.binpb"), r.expr.clone())).collect();
        let mut dirs: Vec<_> = fs::read_dir(root().join("generated/checked"))?.flatten().map(|e| e.path()).collect();
        dirs.sort();
        for dir in dirs.iter().filter(|d| !d.ends_with("rust-cel-core")) {
            let writer = dir.file_name().unwrap().to_string_lossy().to_string();
            let entries = match profile.read_bundle(dir, &sources) {
                Ok(entries) => entries,
                Err(e) => {
                    self.record("bundle", &writer, (false, format!("refused: {e}")), None);
                    continue;
                }
            };
            for (name, bytes) in entries {
                let i: usize = name.trim_start_matches("accept-").trim_end_matches(".binpb").parse()?;
                let want = Value::Bool(demo.accept[i].expect.unwrap_or(true));
                let got = unwrap_any(&bytes).and_then(|checked| eval_shipped(&self.env, &self.act, &checked));
                let ok = matches!(&got, Ok(v) if *v == want);
                self.record("shipped", &name, (ok, format!("{got:?}")), Some(&writer));
            }
        }
        Ok(())
    }

    /// A bundle from another profile, and an entry whose source changed, must both be refused.
    fn tampered(&mut self, profile: &Profile, dir: &Path) -> Result<()> {
        let own: cel_neutral_rs::Bundle = serde_json::from_slice(&fs::read(dir.join("bundle.json"))?)?;
        let mut other = own.clone();
        other.profile_sha256 = "0".repeat(64);
        let edited: BTreeMap<_, _> = own.entries.iter().map(|e| (e.file.clone(), "edited".to_string())).collect();
        for (what, bundle, sources) in [("other profile", &other, BTreeMap::new()), ("stale source", &own, edited)] {
            let outcome = match profile.verify_bundle(dir, bundle, &sources) {
                Err(e) => (true, format!("refused: {e}")),
                Ok(_) => (false, "accepted".to_string()),
            };
            self.record("bundle", what, outcome, None);
        }
        Ok(())
    }
}

fn cel_core_demo(demo: &Demo, profile: &Profile, json: &serde_json::Value) -> Result<usize> {
    let pool = DescriptorPool::decode(profile.descriptor_set.as_slice())?;
    let mut run = Run { env: env_from_profile(profile)?, act: activation(&pool, profile, json)?, records: vec![] };
    let out = root().join("generated/checked/rust-cel-core");
    fs::create_dir_all(&out)?;
    let sources = run.cases(demo, &out)?;
    profile.write_bundle(&out, &[("engine", ENGINE), ("version", "0.5.1"), ("options", "profile manifest")], &sources)?;
    run.tampered(profile, &out)?;
    run.shipped(profile, demo)?;
    write_results(&root(), ENGINE, &run.records)?;
    let failures = run.records.iter().filter(|r| !r.ok).count();
    println!("{ENGINE}: {failures} failures, profile {:.12}", profile.digest);
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
    let profile = load_profile(&generated, &demo.scope)?;
    let json: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(generated.join(format!("activation/{}.json", demo.scope)))?)?;
    let failures = cel_core_demo(&demo, &profile, &json)?;
    cel_rust_demo(&demo, &json)?;
    std::process::exit(i32::from(failures > 0));
}
