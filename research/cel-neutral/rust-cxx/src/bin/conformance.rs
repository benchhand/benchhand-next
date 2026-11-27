// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

//! Run the shared conformance suite on cel-cxx 0.2.5 (cel-cpp) and write results/cel-cxx.jsonl.
//!
//! cel-cxx doesn't read conformance/env.yaml, so this maps each extension it names onto a builder flag.
//! Its only entry point compiles with the checker, so a disableCheck test is checked here as well.

use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};

use anyhow::Result;
use base64::Engine as _;
use cel_cxx::{Activation, Env, MapKey, Value};
use serde::Deserialize;
use serde_json::{Value as Json, json};

#[derive(Deserialize)]
struct Test {
    name: String,
    expr: String,
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

fn key_json(k: &MapKey) -> Json {
    match k {
        MapKey::Bool(b) => json!({"boolValue": b}),
        MapKey::Int(i) => json!({"int64Value": i.to_string()}),
        MapKey::Uint(u) => json!({"uint64Value": u.to_string()}),
        MapKey::String(s) => json!({"stringValue": s.as_ref() as &str}),
    }
}

fn value_json(v: &Value) -> Json {
    match v {
        Value::Null => json!({"nullValue": null}),
        Value::Bool(b) => json!({"boolValue": b}),
        Value::Int(i) => json!({"int64Value": i.to_string()}),
        Value::Uint(u) => json!({"uint64Value": u.to_string()}),
        Value::Double(d) => json!({"doubleValue": double(*d)}),
        Value::String(s) => json!({"stringValue": s.as_ref() as &str}),
        Value::Bytes(b) => json!({"bytesValue": base64::engine::general_purpose::STANDARD.encode(b.as_ref() as &[u8])}),
        Value::List(items) => json!({"listValue": {"values": items.iter().map(value_json).collect::<Vec<_>>()}}),
        Value::Map(m) => {
            let entries: Vec<_> = m.iter().map(|(k, v)| json!({"key": key_json(k), "value": value_json(v)})).collect();
            json!({"mapValue": {"entries": entries}})
        }
        other => json!({"unsupported": format!("{other:?}")}),
    }
}

fn main() -> Result<()> {
    let suite: Vec<SuiteFile> = serde_json::from_str(&fs::read_to_string(root().join("suite.json"))?)?;
    let env = Env::builder()
        .with_ext_strings(true)
        .with_ext_math(true)
        .with_ext_encoders(true)
        .with_optional(true)
        .with_ext_bindings(true)
        .with_ext_lists(true)
        .with_ext_comprehensions(true)
        .build()?;
    let activation = Activation::new();
    let mut out = fs::File::create(root().join("results/cel-cxx.jsonl"))?;
    for file in &suite {
        for section in &file.sections {
            for t in &section.tests {
                let result = match env.compile(&t.expr) {
                    Err(e) => json!({"outcome": "check_error", "message": first_line(e)}),
                    Ok(p) => match p.evaluate(&activation) {
                        Err(e) => json!({"outcome": "eval_error", "message": first_line(e)}),
                        Ok(Value::Error(e)) => json!({"outcome": "eval_error", "message": first_line(e)}),
                        Ok(v) => json!({"outcome": "value", "value": value_json(&v)}),
                    },
                };
                let mut row = json!({"file": file.name, "section": section.name, "name": t.name});
                row.as_object_mut().unwrap().extend(result.as_object().unwrap().clone());
                writeln!(out, "{row}")?;
            }
        }
    }
    Ok(())
}
