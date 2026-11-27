// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

//! Run the shared conformance suite on cel-core 0.5.1 and cel 0.16.1, and write
//! results/cel-core.jsonl and results/cel-rust.jsonl.
//!
//! Neither reads conformance/env.yaml, so this maps each extension it names onto the crate's own. cel-core
//! has strings, math, encoders and optionals; its parser carries cel.bind and the two-variable macros.
//! cel 0.16.1 has every extension the file names but no checker, so its tests all run unchecked.

use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::Result;
use base64::Engine as _;
use serde::Deserialize;
use serde_json::{Value as Json, json};

#[derive(Deserialize)]
struct Test {
    name: String,
    expr: String,
    #[serde(default, rename = "disableCheck")]
    disable_check: bool,
}

#[derive(Deserialize)]
struct Section {
    name: String,
    tests: Vec<Test>,
}

#[derive(Deserialize)]
struct SuiteFile {
    name: String,
    sections: Vec<Section>,
}

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("conformance")
}

fn first_line(s: impl ToString) -> String {
    s.to_string().lines().next().unwrap_or("").to_string()
}

fn double(x: f64) -> Json {
    if x.is_nan() {
        json!("NaN")
    } else if x.is_infinite() {
        json!(if x > 0.0 { "Infinity" } else { "-Infinity" })
    } else {
        json!(x)
    }
}

fn bytes(b: &[u8]) -> Json {
    json!({"bytesValue": base64::engine::general_purpose::STANDARD.encode(b)})
}

fn core_json(v: &cel_core::Value) -> Json {
    use cel_core::{MapKey, Value};
    match v {
        Value::Null => json!({"nullValue": null}),
        Value::Bool(b) => json!({"boolValue": b}),
        Value::Int(i) => json!({"int64Value": i.to_string()}),
        Value::UInt(u) => json!({"uint64Value": u.to_string()}),
        Value::Double(d) => json!({"doubleValue": double(*d)}),
        Value::String(s) => json!({"stringValue": s.as_ref()}),
        Value::Bytes(b) => bytes(b),
        Value::List(items) => json!({"listValue": {"values": items.iter().map(core_json).collect::<Vec<_>>()}}),
        Value::Map(m) => {
            let key = |k: &MapKey| match k {
                MapKey::Bool(b) => json!({"boolValue": b}),
                MapKey::Int(i) => json!({"int64Value": i.to_string()}),
                MapKey::UInt(u) => json!({"uint64Value": u.to_string()}),
                MapKey::String(s) => json!({"stringValue": s.as_ref()}),
            };
            let entries: Vec<_> = m.iter().map(|(k, v)| json!({"key": key(k), "value": core_json(v)})).collect();
            json!({"mapValue": {"entries": entries}})
        }
        other => json!({"unsupported": format!("{other:?}")}),
    }
}

fn run_core(env: &cel_core::Env, t: &Test) -> Json {
    let ast = match env.parse_only(&t.expr) {
        Ok(ast) => ast,
        Err(e) => return json!({"outcome": "parse_error", "message": first_line(e)}),
    };
    let ast = if t.disable_check {
        ast
    } else {
        match env.compile(&t.expr) {
            Ok(ast) => ast,
            Err(e) => return json!({"outcome": "check_error", "message": first_line(e)}),
        }
    };
    match env.program(&ast).map(|p| p.eval(&cel_core::EmptyActivation)) {
        Err(e) => json!({"outcome": "eval_error", "message": first_line(e)}),
        Ok(cel_core::Value::Error(e)) => json!({"outcome": "eval_error", "message": first_line(e)}),
        Ok(v) => json!({"outcome": "value", "value": core_json(&v)}),
    }
}

fn rust_json(v: &cel::Value) -> Json {
    use cel::Value;
    use cel::objects::Key;
    match v {
        Value::Null => json!({"nullValue": null}),
        Value::Bool(b) => json!({"boolValue": b}),
        Value::Int(i) => json!({"int64Value": i.to_string()}),
        Value::UInt(u) => json!({"uint64Value": u.to_string()}),
        Value::Float(d) => json!({"doubleValue": double(*d)}),
        Value::String(s) => json!({"stringValue": s.as_str()}),
        Value::Bytes(b) => bytes(b),
        Value::List(items) => json!({"listValue": {"values": items.iter().map(rust_json).collect::<Vec<_>>()}}),
        Value::Map(m) => {
            let key = |k: &Key| match k {
                Key::Bool(b) => json!({"boolValue": b}),
                Key::Int(i) => json!({"int64Value": i.to_string()}),
                Key::Uint(u) => json!({"uint64Value": u.to_string()}),
                Key::String(s) => json!({"stringValue": s.as_str()}),
            };
            let entries: Vec<_> = m.map.iter().map(|(k, v)| json!({"key": key(k), "value": rust_json(v)})).collect();
            json!({"mapValue": {"entries": entries}})
        }
        other => json!({"unsupported": format!("{other:?}")}),
    }
}

fn run_rust(env: &Arc<cel::Env>, t: &Test) -> Json {
    let program = match env.compile(&t.expr) {
        Ok(p) => p,
        Err(e) => return json!({"outcome": "parse_error", "message": first_line(e)}),
    };
    let ctx = cel::Context::with_env(env.clone());
    match program.execute(&ctx) {
        Ok(v) => json!({"outcome": "value", "value": rust_json(&v)}),
        Err(e) => json!({"outcome": "eval_error", "message": first_line(e)}),
    }
}

fn write(suite: &[SuiteFile], engine: &str, run: impl Fn(&Test) -> Json) -> Result<()> {
    let mut out = fs::File::create(root().join(format!("results/{engine}.jsonl")))?;
    for file in suite {
        for section in &file.sections {
            for t in &section.tests {
                let mut row = json!({"file": file.name, "section": section.name, "name": t.name});
                row.as_object_mut().unwrap().extend(run(t).as_object().unwrap().clone());
                writeln!(out, "{row}")?;
            }
        }
    }
    Ok(())
}

fn main() -> Result<()> {
    let suite: Vec<SuiteFile> = serde_json::from_str(&fs::read_to_string(root().join("suite.json"))?)?;

    // The registry carries the well-known types (wrappers, Value, Timestamp), which some tests construct.
    let core = cel_core::Env::with_standard_library()
        .with_proto_registry(Arc::new(cel_core_proto::ProstProtoRegistry::new()))
        .with_extension(cel_core::ext::string_extension())
        .with_extension(cel_core::ext::math_extension())
        .with_extension(cel_core::ext::encoders_extension())
        .with_extension(cel_core::ext::optionals_extension());
    write(&suite, "cel-core", |t| run_core(&core, t))?;

    let mut rust = cel::Env::stdlib();
    for ext in [
        cel::extensions::strings,
        cel::extensions::math,
        cel::extensions::encoders,
        cel::extensions::bindings,
        cel::extensions::lists,
        cel::extensions::two_var_comprehensions,
    ] {
        rust.add_extension(ext)?;
    }
    let rust = Arc::new(rust);
    // One test panicking inside the crate would end the run, so each runs behind catch_unwind.
    write(&suite, "cel-rust", |t| {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run_rust(&rust, t)))
            .unwrap_or_else(|_| json!({"outcome": "eval_error", "message": "panic"}))
    })?;
    Ok(())
}
