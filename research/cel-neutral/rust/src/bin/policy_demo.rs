//! Evaluate the compiled cel-policy CheckedExprs (generated/checked-policy/*.binpb) on cel-core 0.5.1.
//!
//! cel-go's policy compiler wrote them (../go-policy); cel-core has no policy support, so this runs the
//! shipped CheckedExpr on the cases in policy/tests.json.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context as _, Result};
use cel_core::{Ast, MapActivation, Value};
use cel_core_proto::{CheckedExpr, ParsedExpr, ProstMessage, check_result_from_proto, from_parsed_expr};
use cel_neutral_rs::{EnvConfig, env_from_config};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn strings(v: &Value) -> Option<Vec<String>> {
    match v {
        Value::List(items) => items
            .iter()
            .map(|i| match i {
                Value::String(s) => Some(s.to_string()),
                _ => None,
            })
            .collect(),
        _ => None,
    }
}

fn main() -> Result<()> {
    let root = root();
    let fds = fs::read(root.join("generated/types.binpb"))?;
    let config: EnvConfig = serde_yaml::from_str(&fs::read_to_string(root.join("policy/env.yaml"))?)?;
    let env = env_from_config(&config, &fds)?;
    let pool = DescriptorPool::decode(fds.as_slice())?;
    let part = pool.get_message_by_name("benchhand.contracts.record.part.Part").context("Part")?;
    let tests: Vec<serde_json::Value> = serde_json::from_str(&fs::read_to_string(root.join("policy/tests.json"))?)?;
    let mut failures = 0;
    for entry in fs::read_dir(root.join("generated/checked-policy"))? {
        let path = entry?.path();
        let name = path.file_stem().unwrap().to_string_lossy().to_string();
        let any = prost_types::Any::decode(fs::read(&path)?.as_slice())?;
        let checked = CheckedExpr::decode(any.value.as_slice())?;
        let parsed = ParsedExpr { expr: checked.expr.clone(), source_info: checked.source_info.clone() };
        let program = from_parsed_expr(&parsed)
            .map_err(anyhow::Error::from)
            .and_then(|expr| Ok(Ast::new_checked(expr, "", check_result_from_proto(&checked)?)))
            .and_then(|ast| Ok(env.program(&ast)?));
        let program = match program {
            Ok(p) => p,
            Err(e) => {
                println!("BAD {name}: program failed: {e}");
                failures += tests.len();
                continue;
            }
        };
        for case in &tests {
            let b = &case["bindings"];
            let mut act = MapActivation::new();
            act.insert("stage", Value::from(b["stage"].as_str().unwrap_or_default()));
            act.insert("iteration", Value::from(b["iteration"].as_str().unwrap_or_default()));
            let part_json = b["part"].to_string();
            let mut de = serde_json::Deserializer::from_str(&part_json);
            let msg = DynamicMessage::deserialize(part.clone(), &mut de)?;
            act.insert("part", Value::Message(Box::new(ProstMessage::new(msg))));
            let got = program.eval(&act);
            let want: Vec<String> = serde_json::from_value(case["expected"].clone())?;
            let ok = strings(&got).as_ref() == Some(&want);
            failures += usize::from(!ok);
            println!("{} {name} {} -> {got:?}", if ok { "ok " } else { "BAD" }, case["testCase"]);
        }
    }
    println!("cel-core policy: {failures} failures");
    std::process::exit(i32::from(failures > 0));
}
