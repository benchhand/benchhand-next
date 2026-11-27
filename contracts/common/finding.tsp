// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/common/finding/")
namespace Common.Finding;

/** One problem a service reports, such as a record validation finding. code is stable and names the rule; message is for people and may change. error blocks; warning and info never do */
@summary("benchhand finding")
@id("https://benchhand.github.io/benchhand/contracts/common/finding.schema.json")
@extension("x-version", "1.0.0")
model Finding {
  @pattern("^[a-z][a-z0-9]*(\\.[a-z0-9_]+)+$")
  code: string;

  severity: "error" | "warning" | "info";

  /** The file the finding is about, relative to the project root, with / separators */
  @minLength(1)
  @pattern("^[^/\\\\][^\\\\]*$")
  @extension("not", #{ pattern: "(^|/)\\.\\.(/|$)" })
  path: string;

  /** A JSON Pointer (RFC 6901) into the document at path; for a CSV file /<row index>/<column> */
  @pattern("^(/([^~/]|~[01])*)*$")
  pointer?: string;

  @minLength(1)
  message: string;

  /** What fixes it */
  @minLength(1)
  action?: string;

  /** What the finding is about, for grouping: a part number or a document id */
  @minLength(1)
  subject?: string;
}

@@example(
  Finding,
  #{
    code: "record.version_unsupported",
    severity: "error",
    path: "hw/product.yaml",
    pointer: "/record_version",
    message: "record_version 2 is not supported; this release reads record_version 3",
    action: "Migrate the record; nothing was changed.",
  }
);
@@example(
  Finding,
  #{
    code: "bom.unknown_part",
    severity: "error",
    path: "hw/bom.csv",
    pointer: "/3/PN",
    message: "BOM PN LMP-0099 has no hw/parts/LMP-0099/part.yaml and is not an assembly",
    subject: "LMP-0099",
  }
);
