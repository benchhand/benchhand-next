//! Shared pieces of the Rust harness: the cel-go environment YAML, read into cel-core declarations.
//!
//! Neither Rust engine reads the env YAML or a descriptor set by itself as an environment. This is the
//! adapter: about 40 lines that map the env YAML's variables and extensions onto cel-core's `Env`, with
//! the message types taken from the generated FileDescriptorSet.

use std::sync::Arc;

use anyhow::{Result, bail};
use cel_core::{CelType, Env};
use cel_core_proto::ProstProtoRegistry;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct EnvConfig {
    pub name: String,
    #[serde(default)]
    pub container: String,
    #[serde(default)]
    pub extensions: Vec<Extension>,
    #[serde(default)]
    pub variables: Vec<Variable>,
}

#[derive(Debug, Deserialize)]
pub struct Extension {
    pub name: String,
}

#[derive(Debug, Deserialize)]
pub struct Variable {
    pub name: String,
    pub type_name: String,
    #[serde(default)]
    pub params: Vec<TypeDesc>,
}

#[derive(Debug, Deserialize)]
pub struct TypeDesc {
    pub type_name: String,
    #[serde(default)]
    pub params: Vec<TypeDesc>,
}

/// The CEL type a cel-go `TypeDesc` names: a primitive, list, map, or a message from the registry.
pub fn cel_type(type_name: &str, params: &[TypeDesc]) -> Result<CelType> {
    let param = |i: usize| -> Result<CelType> {
        let p = params.get(i).ok_or_else(|| anyhow::anyhow!("{type_name} needs a parameter {i}"))?;
        cel_type(&p.type_name, &p.params)
    };
    Ok(match type_name {
        "bool" => CelType::Bool,
        "int" => CelType::Int,
        "uint" => CelType::UInt,
        "double" => CelType::Double,
        "string" => CelType::String,
        "bytes" => CelType::Bytes,
        "null_type" => CelType::Null,
        "dyn" => CelType::Dyn,
        "timestamp" | "google.protobuf.Timestamp" => CelType::Timestamp,
        "duration" | "google.protobuf.Duration" => CelType::Duration,
        "list" => CelType::list(param(0)?),
        "map" => CelType::map(param(0)?, param(1)?),
        other if other.contains('.') => CelType::message(other),
        other => bail!("unsupported type_name {other}"),
    })
}

/// A cel-core environment from the env YAML and a FileDescriptorSet.
pub fn env_from_config(config: &EnvConfig, descriptor_set: &[u8]) -> Result<Env> {
    let mut registry = ProstProtoRegistry::new();
    registry.add_file_descriptor_set(descriptor_set).map_err(|e| anyhow::anyhow!(e))?;
    let mut env = Env::with_standard_library().with_proto_registry(Arc::new(registry));
    if !config.container.is_empty() {
        env = env.with_container(config.container.clone());
    }
    for ext in &config.extensions {
        env = match ext.name.as_str() {
            "strings" => env.with_extension(cel_core::ext::string_extension()),
            "optional" => env.with_extension(cel_core::ext::optionals_extension()),
            "math" => env.with_extension(cel_core::ext::math_extension()),
            "encoders" => env.with_extension(cel_core::ext::encoders_extension()),
            other => bail!("cel-core has no extension {other}"),
        };
    }
    for var in &config.variables {
        env = env.with_variable(var.name.clone(), cel_type(&var.type_name, &var.params)?);
    }
    Ok(env)
}
