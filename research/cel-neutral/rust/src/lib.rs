//! Shared pieces of the Rust harness: the cel-go environment YAML, read into cel-core declarations.
//!
//! Neither Rust engine reads the env YAML or a descriptor set by itself as an environment. This is the
//! adapter: about 40 lines that map the env YAML's variables and extensions onto cel-core's `Env`, with
//! the message types taken from the generated FileDescriptorSet.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;

use anyhow::{Result, bail};
use cel_core::{CelType, Env};
use cel_core_proto::ProstProtoRegistry;
use serde::{Deserialize, Serialize};

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
            // cel.bind and cel.block are standard macros in cel-core's parser, so there is nothing to add.
            "bindings" => env,
            other => bail!("cel-core has no extension {other}"),
        };
    }
    for var in &config.variables {
        env = env.with_variable(var.name.clone(), cel_type(&var.type_name, &var.params)?);
    }
    Ok(env)
}

// ---- The environment profile: the manifest is the only input to the environment.

/// generated/profile/<name>.profile.json, written by gen/profile.py.
#[derive(Debug, Deserialize)]
pub struct Manifest {
    pub name: String,
    pub descriptor_set: DescriptorRef,
    #[serde(default)]
    pub container: String,
    pub variables: Vec<ManifestVariable>,
    pub extensions: Vec<ManifestExtension>,
    pub options: ProfileOptions,
    pub checkers_of_record: Vec<Checker>,
}

/// The checker that wrote a bundle: an engine and its pinned version.
#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct Checker {
    pub engine: String,
    pub version: String,
}

#[derive(Debug, Deserialize)]
pub struct DescriptorRef {
    pub file: String,
    pub sha256: String,
}

#[derive(Debug, Deserialize)]
pub struct ManifestVariable {
    pub name: String,
    #[serde(rename = "type")]
    pub type_name: String,
}

#[derive(Debug, Deserialize)]
pub struct ManifestExtension {
    pub name: String,
    pub version: u32,
}

#[derive(Debug, Deserialize, PartialEq)]
pub struct ProfileOptions {
    pub cross_type_numeric_comparisons: bool,
    pub homogeneous_aggregate_literals: bool,
}

/// A loaded manifest, its digest, and the descriptor set it names.
pub struct Profile {
    pub manifest: Manifest,
    pub digest: String,
    pub descriptor_set: Vec<u8>,
}

/// What the cel-core adapter implements, in cel-go's extension numbering. cel-core has no version
/// switch; these are the versions whose functions the shared suite exercised on it. Bindings is 0:
/// the `cel.bind` macro works, but cel-core doesn't evaluate the `cel.@block` call of version 1.
const CEL_CORE_EXTENSIONS: &[(&str, &[u32])] =
    &[("strings", &[4]), ("optional", &[2]), ("math", &[1]), ("encoders", &[0]), ("bindings", &[0])];
/// cel-core's checker defaults; it has no switch for them.
const CEL_CORE_OPTIONS: ProfileOptions =
    ProfileOptions { cross_type_numeric_comparisons: false, homogeneous_aggregate_literals: false };

pub fn sha256_hex(data: &[u8]) -> String {
    use sha2::Digest as _;
    hex::encode(sha2::Sha256::digest(data))
}

/// The profile digest: SHA-256 of the manifest's RFC 8785 (JCS) encoding. For the manifest's ASCII,
/// integer-only subset that is serde_json's sorted-key compact form (no `preserve_order` feature).
pub fn profile_digest(raw: &[u8]) -> Result<String> {
    let value: serde_json::Value = serde_json::from_slice(raw)?;
    Ok(sha256_hex(serde_json::to_string(&value)?.as_bytes()))
}

pub fn load_profile(generated: &Path, name: &str) -> Result<Profile> {
    let raw = fs::read(generated.join(format!("profile/{name}.profile.json")))?;
    let manifest: Manifest = serde_json::from_slice(&raw)?;
    let descriptor_set = fs::read(generated.join(&manifest.descriptor_set.file))?;
    if sha256_hex(&descriptor_set) != manifest.descriptor_set.sha256 {
        bail!("{name}: the descriptor set doesn't match the manifest's SHA-256");
    }
    for ext in &manifest.extensions {
        let known = CEL_CORE_EXTENSIONS.iter().find(|(n, _)| *n == ext.name);
        if !known.is_some_and(|(_, versions)| versions.contains(&ext.version)) {
            bail!("{name}: cel-core has no {} version {}", ext.name, ext.version);
        }
    }
    if manifest.options != CEL_CORE_OPTIONS {
        bail!("{name}: options {:?} differ from cel-core's {:?}", manifest.options, CEL_CORE_OPTIONS);
    }
    Ok(Profile { digest: profile_digest(&raw)?, manifest, descriptor_set })
}

/// The cel-core environment for a profile: its declarations and extensions, nothing else.
pub fn env_from_profile(profile: &Profile) -> Result<Env> {
    let m = &profile.manifest;
    let config = EnvConfig {
        name: m.name.clone(),
        container: m.container.clone(),
        extensions: m.extensions.iter().map(|e| Extension { name: e.name.clone() }).collect(),
        variables: m
            .variables
            .iter()
            .map(|v| Variable { name: v.name.clone(), type_name: v.type_name.clone(), params: vec![] })
            .collect(),
    };
    env_from_config(&config, &profile.descriptor_set)
}

/// bundle.json beside a directory of CheckedExprs. Its identity is the profile digest, the checker, and
/// the SHA-256 of each entry's exact payload bytes.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Bundle {
    pub profile_sha256: String,
    pub checker: Checker,
    pub entries: Vec<BundleEntry>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BundleEntry {
    pub file: String,
    pub payload_sha256: String,
    pub source_sha256: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

fn dir_name(dir: &Path) -> String {
    dir.file_name().unwrap_or_default().to_string_lossy().to_string()
}

pub fn load_bundle(dir: &Path) -> Result<Bundle> {
    let raw = fs::read(dir.join("bundle.json"))
        .map_err(|_| anyhow::anyhow!("{}: no bundle.json, so the profile is unknown", dir_name(dir)))?;
    Ok(serde_json::from_slice(&raw)?)
}

impl Profile {
    /// Writes dir/bundle.json for the payload files already in dir and their sources.
    pub fn write_bundle(&self, dir: &Path, checker: Checker, sources: &BTreeMap<String, String>) -> Result<()> {
        let mut entries = vec![];
        for (file, src) in sources {
            entries.push(BundleEntry {
                file: file.clone(),
                payload_sha256: sha256_hex(&fs::read(dir.join(file))?),
                source_sha256: sha256_hex(src.as_bytes()),
                source: None,
            });
        }
        let bundle = Bundle { profile_sha256: self.digest.clone(), checker, entries };
        fs::write(dir.join("bundle.json"), serde_json::to_string_pretty(&bundle)? + "\n")?;
        Ok(())
    }

    pub fn is_checker_of_record(&self, checker: &Checker) -> bool {
        self.manifest.checkers_of_record.contains(checker)
    }

    /// verify_bundle on dir/bundle.json, requiring a checker of record.
    pub fn read_bundle(
        &self,
        dir: &Path,
        sources: Option<&BTreeMap<String, String>>,
    ) -> Result<BTreeMap<String, Vec<u8>>> {
        self.verify_bundle(dir, &load_bundle(dir)?, sources, true)
    }

    /// Each entry's payload, after checking the profile digest, the checker of record (when required),
    /// each payload's SHA-256, and each source's SHA-256 when sources is given. An evaluator that has only
    /// the bundle passes None: the producer verified the sources, and the host does again at load.
    pub fn verify_bundle(
        &self,
        dir: &Path,
        bundle: &Bundle,
        sources: Option<&BTreeMap<String, String>>,
        require_checker_of_record: bool,
    ) -> Result<BTreeMap<String, Vec<u8>>> {
        let name = dir_name(dir);
        if bundle.profile_sha256 != self.digest {
            bail!("{name}: checked in profile {:.12}, not {:.12}", bundle.profile_sha256, self.digest);
        }
        if require_checker_of_record && !self.is_checker_of_record(&bundle.checker) {
            bail!("{name}: {} {} isn't a checker of record", bundle.checker.engine, bundle.checker.version);
        }
        let mut out = BTreeMap::new();
        for entry in &bundle.entries {
            let payload = fs::read(dir.join(&entry.file))?;
            if sha256_hex(&payload) != entry.payload_sha256 {
                bail!("{name}/{}: the payload isn't the one the checker shipped", entry.file);
            }
            if let Some(sources) = sources {
                match sources.get(&entry.file) {
                    Some(src) if sha256_hex(src.as_bytes()) == entry.source_sha256 => {}
                    _ => bail!("{name}/{}: stale, the source changed since it was checked", entry.file),
                }
            }
            out.insert(entry.file.clone(), payload);
        }
        Ok(out)
    }
}

/// One outcome in results/typed-demo/<engine>.json.
#[derive(Debug, Serialize)]
pub struct Record {
    pub engine: String,
    pub kind: String,
    pub case: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub writer: Option<String>,
    pub ok: bool,
    pub detail: String,
}

pub fn write_results(root: &Path, name: &str, records: &[Record]) -> Result<()> {
    let dir = root.join("results/typed-demo");
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(format!("{name}.json")), serde_json::to_string_pretty(records)? + "\n")?;
    Ok(())
}
