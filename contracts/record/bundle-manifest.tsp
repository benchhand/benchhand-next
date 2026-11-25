import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/bundle-manifest/")
namespace Records.BundleManifest;

/** Provisional: the manifest.json of a sealed directory, a built version (hw/versions/<V>/) or a version-bound bundle such as hw/checks/<V>/<S>/, with only the keys the evidence service reads. Phase 2's versioning work (snapshot, seal and verify) owns this contract and extends it; until then every other key is accepted unread */
@summary("benchhand sealed directory manifest (manifest.json), provisional")
@id("https://benchhand.github.io/benchhand/contracts/record/bundle-manifest.schema.json")
@extension("x-version", "0.1.0")
model BundleManifest {
  /** sha256 of every file the directory holds apart from manifest.json, by its path relative to the directory */
  files: Record<Common.sha256>;

  /** a bundle's binding to its build: the sha256 of hw/versions/<V>/manifest.json */
  version_manifest_sha256?: Common.sha256;

  /** a built version's parts, by PN */
  parts?: Record<version_part>;

  ...Record<unknown>;
}

model version_part {
  /** sha256 of the model source the version built */
  source_sha256?: Common.sha256;

  ...Record<unknown>;
}

@@example(
  BundleManifest,
  #{
    files: #{
      `result.json`: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    },
    version_manifest_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  }
);
