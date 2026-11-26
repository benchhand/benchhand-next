//! Evaluate the compiled cel-policy bundles (generated/checked-policy/<profile>/) on cel-core 0.5.1.
//!
//! The reference checker (go/celcheck) wrote them; cel-core has no policy support, so this runs the
//! shipped CheckedExprs on the cases in policy/tests.json. Each bundle directory is named after the
//! profile it was compiled in: the environment is built from that manifest, and the bundle is refused
//! when the profile digest differs, when the adapter can't implement the profile, or when a .celpolicy
//! source changed since it was compiled.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context as _, Result};
use cel_core::{Ast, MapActivation, Value};
use cel_core_proto::{CheckedExpr, ParsedExpr, ProstMessage, check_result_from_proto, from_parsed_expr};
use cel_neutral_rs::{Bundle, Record, env_from_profile, load_profile, write_results};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};

const ENGINE: &str = "cel-core";

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

fn record(records: &mut Vec<Record>, kind: &str, case: String, ok: bool, detail: String) {
    println!("{} {kind} {case}: {detail}", if ok { "ok " } else { "BAD" });
    records.push(Record { engine: ENGINE.into(), kind: kind.into(), case, writer: None, ok, detail });
}

fn run_bundle(dir: &Path, tests: &[serde_json::Value], records: &mut Vec<Record>) -> Result<()> {
    let name = dir.file_name().unwrap().to_string_lossy().to_string();
    let bundle: Bundle = serde_json::from_slice(&fs::read(dir.join("bundle.json"))?)?;
    let mut sources = BTreeMap::new();
    for e in &bundle.entries {
        let src = e.source.as_ref().context("a policy entry names its source file")?;
        sources.insert(e.file.clone(), fs::read_to_string(root().join(src))?);
    }
    let loaded = load_profile(&root().join("generated"), &name)
        .and_then(|profile| Ok((profile.read_bundle(dir, &sources)?, profile)));
    let (entries, profile) = match loaded {
        Ok(v) => v,
        Err(e) => {
            record(records, "bundle", name, false, format!("refused: {e}"));
            return Ok(());
        }
    };
    let env = env_from_profile(&profile)?;
    let pool = DescriptorPool::decode(profile.descriptor_set.as_slice())?;
    let part_type = &profile.manifest.variables.iter().find(|v| v.name == "part").context("part")?.type_name;
    let part = pool.get_message_by_name(part_type).context("Part")?;
    for (file, bytes) in entries {
        let any = prost_types::Any::decode(bytes.as_slice())?;
        let checked = CheckedExpr::decode(any.value.as_slice())?;
        let parsed = ParsedExpr { expr: checked.expr.clone(), source_info: checked.source_info.clone() };
        let ast = Ast::new_checked(from_parsed_expr(&parsed)?, "", check_result_from_proto(&checked)?);
        let program = env.program(&ast)?;
        for case in tests {
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
            let id = format!("{name}/{file} {}", case["testCase"].as_str().unwrap_or_default());
            record(records, "policy", id, strings(&got).as_ref() == Some(&want), format!("{got:?}"));
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let root = root();
    let tests: Vec<serde_json::Value> = serde_json::from_str(&fs::read_to_string(root.join("policy/tests.json"))?)?;
    let mut records = vec![];
    let mut dirs: Vec<_> = fs::read_dir(root.join("generated/checked-policy"))?
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    dirs.sort();
    for dir in dirs {
        run_bundle(&dir, &tests, &mut records)?;
    }
    write_results(&root, &format!("policy-{ENGINE}"), &records)?;
    let failures = records.iter().filter(|r| !r.ok).count();
    println!("{ENGINE} policy: {failures} failures");
    std::process::exit(i32::from(failures > 0));
}
