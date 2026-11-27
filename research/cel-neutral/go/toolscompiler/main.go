// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// toolscompiler runs the gate_guard profile cases through cel-go's tools/compiler package, loading the
// generated env YAML and descriptor set with EnvironmentFile and TypeDescriptorSetFile. It shows why that
// package isn't the reference checker: NewCompiler always adds the latest optional and bindings
// extensions, so excluded syntax checks. It writes results/typed-demo/tools-compiler.json.
//
// Usage (from research/cel-neutral/go): go run ./toolscompiler
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"celneutral/go/profile"

	"cel.dev/cel-go/tools/compiler"
	"go.yaml.in/yaml/v3"
)

func must[T any](v T, err error) T {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	return v
}

func main() {
	root := must(filepath.Abs(".."))
	var d struct {
		Profile []struct {
			Expr    string `yaml:"expr"`
			Feature string `yaml:"feature"`
			Refuse  bool   `yaml:"refuse"`
		} `yaml:"profile"`
	}
	must(0, yaml.Unmarshal(must(os.ReadFile(filepath.Join(root, "typedemo/gate_guard.yaml"))), &d))
	// TypeDescriptorSetFile infers the format from the extension: .binarypb, .fds or .pb, not buf's .binpb.
	fds := filepath.Join(os.TempDir(), "cel-neutral-types.fds")
	must(0, os.WriteFile(fds, must(os.ReadFile(filepath.Join(root, "generated/types.binpb"))), 0o644))
	defer os.Remove(fds)
	c := must(compiler.NewCompiler(
		compiler.TypeDescriptorSetFile(fds),
		compiler.EnvironmentFile(filepath.Join(root, "generated/env/gate_guard.env.yaml")),
	))
	var records []profile.Record
	for _, r := range d.Profile {
		_, _, err := (&compiler.RawExpression{Value: r.Expr}).CreateAST(c)
		detail := r.Feature + ": checked"
		if err != nil {
			detail = r.Feature + ": " + strings.SplitN(err.Error(), "\n", 2)[0]
		}
		ok := (err != nil) == r.Refuse
		records = append(records, profile.Record{Engine: "tools/compiler", Kind: "profile", Case: r.Expr, OK: ok, Detail: detail})
		fmt.Printf("%s profile %q: %s\n", map[bool]string{true: "ok ", false: "BAD"}[ok], r.Expr, detail)
	}
	must(0, profile.WriteResults(root, "tools-compiler", records))
}
