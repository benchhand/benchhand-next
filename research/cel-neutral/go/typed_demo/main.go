// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// The typed demo on cel-go, the reference engine, built from the gate_guard profile manifest.
//
// It writes each accepted rule's CheckedExpr with a bundle.json (profile digest, checker, payload and
// source digests), evaluates the bundles the other engines wrote after verifying them, runs the profile
// and tampered-bundle cases, and writes every outcome to results/typed-demo/cel-go.json.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"celneutral/go/profile"

	"cel.dev/cel-go/cel"
	"go.yaml.in/yaml/v3"
	exprpb "google.golang.org/genproto/googleapis/api/expr/v1alpha1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/anypb"
)

const engine = "cel-go"

type rule struct {
	Expr    string `yaml:"expr"`
	Expect  any    `yaml:"expect"`
	Why     string `yaml:"why"`
	Feature string `yaml:"feature"`
	Refuse  bool   `yaml:"refuse"`
	Meaning string `yaml:"meaning"`
	Error   bool   `yaml:"error"`
}

type demo struct {
	Scope           string           `yaml:"scope"`
	Accept          []rule           `yaml:"accept"`
	Reject          []rule           `yaml:"reject"`
	Profile         []rule           `yaml:"profile"`
	Presence        []rule           `yaml:"presence"`
	PresenceRecords []presenceRecord `yaml:"presence_records"`
}

// presenceRecord edits one field of an activation record: removes it, sets it to JSON null, or sets it
// to a zero value.
type presenceRecord struct {
	Variable string `yaml:"variable"`
	Field    string `yaml:"field"`
	State    string `yaml:"state"`
	Zero     any    `yaml:"zero"`
	Expr     string `yaml:"expr"`
	Expect   bool   `yaml:"expect"`
}

func must[T any](v T, err error) T {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	return v
}

type run struct {
	env     *cel.Env
	vars    map[string]any
	records []profile.Record
}

func (r *run) record(kind, c string, ok bool, detail, writer string) {
	r.records = append(r.records, profile.Record{Engine: engine, Kind: kind, Case: c, Writer: writer, OK: ok, Detail: detail})
	from := ""
	if writer != "" {
		from = " from " + writer
	}
	fmt.Printf("%s %s%s %q: %s\n", map[bool]string{true: "ok ", false: "BAD"}[ok], kind, from, c, detail)
}

func (r *run) eval(ast *cel.Ast) (any, error) {
	prg, err := r.env.Program(ast)
	if err != nil {
		return nil, err
	}
	out, _, err := prg.Eval(r.vars)
	if err != nil {
		return nil, err
	}
	return out.Value(), nil
}

func firstLine(err error) string { return strings.SplitN(err.Error(), "\n", 2)[0] }

func activation(files *protoregistry.Files, p *profile.Profile, path string) map[string]any {
	var raw map[string]json.RawMessage
	must(0, json.Unmarshal(must(os.ReadFile(path)), &raw))
	out := map[string]any{}
	for _, v := range p.Manifest.Variables {
		out[v.Name] = must(parseRecord(files, v.Type, raw[v.Name]))
	}
	return out
}

// parseRecord turns one JSON record into the declared message with protojson, the activation path.
func parseRecord(files *protoregistry.Files, typeName string, raw []byte) (any, error) {
	desc := must(files.FindDescriptorByName(protoreflect.FullName(typeName)))
	msg := dynamicpb.NewMessage(desc.(protoreflect.MessageDescriptor))
	// Omitted (non-structural) fields aren't declared, so the binding drops them.
	return msg, protojson.UnmarshalOptions{DiscardUnknown: true}.Unmarshal(raw, msg)
}

// presenceRecords runs presence through the activation path: edit a record, parse it, evaluate.
func (r *run) presenceRecords(files *protoregistry.Files, p *profile.Profile, path string, cases []presenceRecord) {
	var base map[string]map[string]any
	must(0, json.Unmarshal(must(os.ReadFile(path)), &base))
	types := map[string]string{}
	for _, v := range p.Manifest.Variables {
		types[v.Name] = v.Type
	}
	kept := r.vars
	defer func() { r.vars = kept }()
	for _, c := range cases {
		name := fmt.Sprintf("%s.%s %s: %s", c.Variable, c.Field, c.State, c.Expr)
		rec := map[string]any{}
		for k, v := range base[c.Variable] {
			rec[k] = v
		}
		switch c.State {
		case "missing":
			delete(rec, c.Field)
		case "null":
			rec[c.Field] = nil
		default:
			rec[c.Field] = c.Zero
		}
		msg, err := parseRecord(files, types[c.Variable], must(json.Marshal(rec)))
		if err != nil {
			r.record("presence_record", name, false, "parser refused: "+err.Error(), "")
			continue
		}
		r.vars = map[string]any{}
		for k, v := range kept {
			r.vars[k] = v
		}
		r.vars[c.Variable] = msg
		ast, iss := r.env.Compile(c.Expr)
		if iss.Err() != nil {
			r.record("presence_record", name, false, firstLine(iss.Err()), "")
			continue
		}
		got, err := r.eval(ast)
		r.record("presence_record", name, err == nil && got == c.Expect, fmt.Sprint(got, err), "")
	}
}

// cases runs accept, reject and profile cases and returns the sources of the CheckedExprs it wrote.
func (r *run) cases(d demo, outDir string) map[string]string {
	sources := map[string]string{}
	for i, c := range d.Accept {
		ast, iss := r.env.Compile(c.Expr)
		if iss.Err() != nil {
			r.record("accept", c.Expr, false, firstLine(iss.Err()), "")
			continue
		}
		got, err := r.eval(ast)
		r.record("accept", c.Expr, err == nil && got == c.Expect, fmt.Sprint(got, err), "")
		// The shipped form is a google.protobuf.Any holding a cel.expr.CheckedExpr, as cel-cpp writes it.
		// cel-go's v1alpha1 CheckedExpr has the same wire format as cel.expr.CheckedExpr.
		checked := must(proto.Marshal(must(cel.AstToCheckedExpr(ast))))
		wrapped := &anypb.Any{TypeUrl: "type.googleapis.com/cel.expr.CheckedExpr", Value: checked}
		name := fmt.Sprintf("accept-%d.binpb", i)
		must(0, os.WriteFile(filepath.Join(outDir, name), must(proto.Marshal(wrapped)), 0o644))
		sources[name] = c.Expr
	}
	for _, c := range d.Reject {
		_, iss := r.env.Compile(c.Expr)
		if iss.Err() != nil {
			r.record("reject", c.Expr, true, firstLine(iss.Err()), "")
		} else {
			r.record("reject", c.Expr, false, "type-checked; expected: "+c.Why, "")
		}
	}
	for _, c := range d.Profile {
		ast, iss := r.env.Compile(c.Expr)
		switch {
		case c.Refuse:
			detail := c.Feature + ": checked, should be refused"
			if iss.Err() != nil {
				detail = c.Feature + ": " + firstLine(iss.Err())
			}
			r.record("profile", c.Expr, iss.Err() != nil, detail, "")
		case iss.Err() != nil:
			r.record("profile", c.Expr, false, fmt.Sprintf("%s: %s", c.Feature, firstLine(iss.Err())), "")
		default:
			got, err := r.eval(ast)
			r.record("profile", c.Expr, err == nil && got == c.Expect, fmt.Sprintf("%s: %v %v", c.Feature, got, err), "")
		}
	}
	r.presence(d.Presence)
	return sources
}

// presence runs the presence cases: missing, zero and null on wrapper, optional and plain fields.
func (r *run) presence(cases []rule) {
	for _, c := range cases {
		ast, iss := r.env.Compile(c.Expr)
		if iss.Err() != nil {
			r.record("presence", c.Expr, false, c.Meaning+": "+firstLine(iss.Err()), "")
			continue
		}
		got, err := r.eval(ast)
		ok := (c.Error && err != nil) || (!c.Error && err == nil && got == c.Expect)
		r.record("presence", c.Expr, ok, fmt.Sprintf("%s: %v %v", c.Meaning, got, err), "")
	}
}

// shipped evaluates the bundles another engine wrote, without parsing or checking them here. A bundle
// from a checker of record is the gate case (kind "shipped"); any other writer's bundle is verified the
// same way except for the checker and evaluated as a portability diagnostic (kind "portability").
func (r *run) shipped(p *profile.Profile, d demo, dir string) {
	sources, expect := map[string]string{}, map[string]any{}
	for i, c := range d.Accept {
		sources[fmt.Sprintf("accept-%d.binpb", i)] = c.Expr
		expect[fmt.Sprintf("accept-%d.binpb", i)] = c.Expect
	}
	writer := filepath.Base(dir)
	b, err := profile.LoadBundle(dir)
	var entries map[string][]byte
	if err == nil {
		entries, err = p.VerifyBundle(dir, b, sources, false)
	}
	if err != nil {
		r.record("bundle", writer, false, "refused: "+err.Error(), "")
		return
	}
	kind := "portability"
	if p.IsCheckerOfRecord(b.Checker) {
		kind = "shipped"
	}
	for name, data := range entries {
		wrapped := &anypb.Any{}
		must(0, proto.Unmarshal(data, wrapped))
		checked := &exprpb.CheckedExpr{}
		must(0, proto.Unmarshal(wrapped.GetValue(), checked))
		got, err := r.eval(cel.CheckedExprToAst(checked))
		r.record(kind, name, err == nil && got == expect[name], fmt.Sprint(got, err), writer)
	}
}

// tampered checks the reference checker's bundle against every way it can be wrong: another profile,
// a stale source, a substituted payload, and a checker that isn't of record. With no sources at all
// (an evaluator that has only the bundle) it must still verify.
func (r *run) tampered(p *profile.Profile, d demo, ref string) {
	own, err := profile.LoadBundle(ref)
	if err != nil {
		r.record("bundle", "reference bundle", false, err.Error(), "")
		return
	}
	sources, edited := map[string]string{}, map[string]string{}
	for i, c := range d.Accept {
		sources[fmt.Sprintf("accept-%d.binpb", i)] = c.Expr
		edited[fmt.Sprintf("accept-%d.binpb", i)] = "edited"
	}
	other := own
	other.ProfileSHA256 = strings.Repeat("0", 64)
	notRecord := own
	notRecord.Checker = profile.Checker{Engine: "cel-core", Version: "0.5.1"}
	swapped := substituted(ref)
	defer os.RemoveAll(swapped)
	refuse := []struct {
		what    string
		dir     string
		bundle  profile.Bundle
		sources map[string]string
	}{
		{"other profile", ref, other, sources},
		{"stale source", ref, own, edited},
		{"substituted payload", swapped, own, sources},
		{"not a checker of record", ref, notRecord, sources},
	}
	for _, c := range refuse {
		if _, err := p.VerifyBundle(c.dir, c.bundle, c.sources, true); err != nil {
			r.record("bundle", c.what, true, "refused: "+err.Error(), "")
		} else {
			r.record("bundle", c.what, false, "accepted", "")
		}
	}
	_, err = p.VerifyBundle(ref, own, nil, true)
	r.record("bundle", "evaluator without sources", err == nil, fmt.Sprint("verified: ", err), "")
}

// substituted copies a bundle directory with accept-0's payload replaced by accept-1's: a stale or
// foreign CheckedExpr under current metadata.
func substituted(dir string) string {
	tmp := must(os.MkdirTemp("", "cel-neutral-swap-"))
	for _, e := range must(os.ReadDir(dir)) {
		must(0, os.WriteFile(filepath.Join(tmp, e.Name()), must(os.ReadFile(filepath.Join(dir, e.Name()))), 0o644))
	}
	must(0, os.WriteFile(filepath.Join(tmp, "accept-0.binpb"), must(os.ReadFile(filepath.Join(dir, "accept-1.binpb"))), 0o644))
	return tmp
}

func main() {
	root := must(filepath.Abs(".."))
	gen := filepath.Join(root, "generated")
	var d demo
	must(0, yaml.Unmarshal(must(os.ReadFile(filepath.Join(root, "typedemo/gate_guard.yaml"))), &d))
	p := must(profile.Load(gen, d.Scope))
	files := must(protodesc.NewFiles(p.DescriptorSet))
	r := &run{env: must(cel.NewEnv(p.EnvOptions()...))}
	r.vars = activation(files, p, filepath.Join(gen, "activation", d.Scope+".json"))
	outDir := filepath.Join(gen, "checked", "go")
	must(0, os.MkdirAll(outDir, 0o755))
	sources := r.cases(d, outDir)
	r.presenceRecords(files, p, filepath.Join(gen, "activation", d.Scope+".json"), d.PresenceRecords)
	checker := profile.Checker{Engine: engine, Version: "cel.dev/cel-go v0.33.4"}
	must(0, p.WriteBundle(outDir, checker, sources, nil))
	r.tampered(p, d, filepath.Join(gen, "checked", "cel-go-ref"))
	for _, dir := range must(filepath.Glob(filepath.Join(gen, "checked", "*"))) {
		if filepath.Base(dir) != "go" {
			r.shipped(p, d, dir)
		}
	}
	must(0, profile.WriteResults(root, engine, r.records))
	failures := 0
	for _, rec := range r.records {
		if !rec.OK {
			failures++
		}
	}
	fmt.Printf("%s: %d failures, profile %.12s\n", engine, failures, p.Digest)
	if failures > 0 {
		os.Exit(1)
	}
}
