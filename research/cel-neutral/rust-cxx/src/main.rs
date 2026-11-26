//! The typed demo on cel-cxx 0.2.5: Rust over cel-cpp, the same checker cel-expr-python wraps.
//!
//! cel-cxx takes the FileDescriptorSet at runtime; it has no env YAML reader and no CheckedExpr I/O, so
//! the variables come from the env YAML here and messages are bound as serialised bytes.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context as _, Result, anyhow};
use cel_cxx::{Activation, Env, StructType, StructValue, Value, ValueType};
use prost::Message;
use prost_reflect::{DescriptorPool, DynamicMessage};
use serde::Deserialize;

#[derive(Deserialize)]
struct Rule {
    expr: String,
    #[serde(default)]
    why: String,
}

#[derive(Deserialize)]
struct Demo {
    scope: String,
    accept: Vec<Rule>,
    reject: Vec<Rule>,
}

#[derive(Deserialize)]
struct EnvConfig {
    #[serde(default)]
    extensions: Vec<Named>,
    variables: Vec<Variable>,
}

#[derive(Deserialize)]
struct Named {
    name: String,
}

#[derive(Deserialize)]
struct Variable {
    name: String,
    type_name: String,
}

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

fn main() -> Result<()> {
    let root = root();
    let demo: Demo = serde_yaml::from_str(&fs::read_to_string(root.join("typedemo/gate_guard.yaml"))?)?;
    let generated = root.join("generated");
    let config: EnvConfig =
        serde_yaml::from_str(&fs::read_to_string(generated.join(format!("env/{}.env.yaml", demo.scope)))?)?;
    let fds = fs::read(generated.join("types.binpb"))?;
    let json: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(generated.join(format!("activation/{}.json", demo.scope)))?)?;

    let mut builder = Env::builder().with_file_descriptor_set(&fds);
    for ext in &config.extensions {
        builder = match ext.name.as_str() {
            "strings" => builder.with_ext_strings(true),
            "optional" => builder.with_optional(true),
            other => return Err(anyhow!("no mapping for extension {other}")),
        };
    }
    for var in &config.variables {
        builder = builder.declare_variable_with_type(&var.name, ValueType::Struct(StructType::new(&var.type_name)))?;
    }
    let env = builder.build()?;

    let pool = DescriptorPool::decode(fds.as_slice())?;
    let mut activation = Activation::new();
    for var in &config.variables {
        let desc = pool.get_message_by_name(&var.type_name).context("message type")?;
        let text = json[&var.name].to_string();
        let mut de = serde_json::Deserializer::from_str(&text);
        let options = prost_reflect::DeserializeOptions::new().deny_unknown_fields(false);
        let msg = DynamicMessage::deserialize_with_options(desc, &mut de, &options)?;
        activation =
            activation.bind_variable_dynamic(&var.name, StructValue::from_bytes(&var.type_name, msg.encode_to_vec()))?;
    }

    let mut failures = 0;
    for rule in &demo.accept {
        let got = env.compile(&rule.expr).and_then(|p| p.evaluate(&activation));
        let ok = matches!(got, Ok(Value::Bool(true)));
        failures += usize::from(!ok);
        println!("{} accept {:?} -> {:?}", if ok { "ok " } else { "BAD" }, rule.expr, got.map(|v| v.to_string()));
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
    println!("cel-cxx: {failures} failures");
    std::process::exit(i32::from(failures > 0));
}
