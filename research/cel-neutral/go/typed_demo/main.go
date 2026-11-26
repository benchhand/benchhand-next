// The typed demo on cel-go, the reference engine, built from the gate_guard profile manifest.
//
// It writes each accepted rule's CheckedExpr with a bundle.json (profile digest, checker, source digests),
// evaluates the bundles the other engines wrote after checking their profile and sources, runs the profile
// cases, and writes every outcome to results/typed-demo/cel-go.json.
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
}

type demo struct {
	Scope   string `yaml:"scope"`
	Accept  []rule `yaml:"accept"`
	Reject  []rule `yaml:"reject"`
	Profile []rule `yaml:"profile"`
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
		desc := must(files.FindDescriptorByName(protoreflect.FullName(v.Type)))
		msg := dynamicpb.NewMessage(desc.(protoreflect.MessageDescriptor))
		// Omitted (non-structural) fields aren't declared, so the binding drops them.
		must(0, protojson.UnmarshalOptions{DiscardUnknown: true}.Unmarshal(raw[v.Name], msg))
		out[v.Name] = msg
	}
	return out
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
	return sources
}

// shipped evaluates the bundles another engine wrote, without parsing or checking them here.
func (r *run) shipped(p *profile.Profile, d demo, dir string) {
	sources, expect := map[string]string{}, map[string]any{}
	for i, c := range d.Accept {
		sources[fmt.Sprintf("accept-%d.binpb", i)] = c.Expr
		expect[fmt.Sprintf("accept-%d.binpb", i)] = c.Expect
	}
	writer := filepath.Base(dir)
	entries, err := p.ReadBundle(dir, sources)
	if err != nil {
		r.record("bundle", writer, false, "refused: "+err.Error(), "")
		return
	}
	for name, data := range entries {
		wrapped := &anypb.Any{}
		must(0, proto.Unmarshal(data, wrapped))
		checked := &exprpb.CheckedExpr{}
		must(0, proto.Unmarshal(wrapped.GetValue(), checked))
		got, err := r.eval(cel.CheckedExprToAst(checked))
		r.record("shipped", name, err == nil && got == expect[name], fmt.Sprint(got, err), writer)
	}
}

// tampered checks that a bundle from another profile, and a stale entry, are both refused.
func (r *run) tampered(p *profile.Profile, dir string) {
	var own profile.Bundle
	must(0, json.Unmarshal(must(os.ReadFile(filepath.Join(dir, "bundle.json"))), &own))
	other := own
	other.ProfileSHA256 = strings.Repeat("0", 64)
	edited := map[string]string{}
	for _, e := range own.Entries {
		edited[e.File] = "edited"
	}
	for what, b := range map[string]profile.Bundle{"other profile": other, "stale source": own} {
		srcs := edited
		if what == "other profile" {
			srcs = map[string]string{}
		}
		if _, err := p.VerifyBundle(dir, b, srcs); err != nil {
			r.record("bundle", what, true, "refused: "+err.Error(), "")
		} else {
			r.record("bundle", what, false, "accepted", "")
		}
	}
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
	checker := map[string]string{"engine": engine, "version": "cel.dev/cel-go v0.33.4", "options": "profile manifest"}
	must(0, p.WriteBundle(outDir, checker, sources, nil))
	r.tampered(p, outDir)
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
