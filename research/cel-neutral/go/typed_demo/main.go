// The typed demo on cel-go, the reference engine: env YAML plus the generated FileDescriptorSet.
//
// It also evaluates the CheckedExprs that cel-expr-python wrote, without re-checking them, and writes its
// own for the other engines.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/google/cel-go/cel"
	"github.com/google/cel-go/common/env"
	"github.com/google/cel-go/ext"
	"go.yaml.in/yaml/v3"
	exprpb "google.golang.org/genproto/googleapis/api/expr/v1alpha1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/reflect/protoregistry"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/dynamicpb"
	"google.golang.org/protobuf/types/known/anypb"
)

type rule struct {
	Expr   string `yaml:"expr"`
	Expect any    `yaml:"expect"`
	Why    string `yaml:"why"`
}

type demo struct {
	Scope  string `yaml:"scope"`
	Accept []rule `yaml:"accept"`
	Reject []rule `yaml:"reject"`
}

func must[T any](v T, err error) T {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	return v
}

func readYAML(path string, out any) {
	must(0, yaml.Unmarshal(must(os.ReadFile(path)), out))
}

func activation(files *protoregistry.Files, conf *env.Config, path string) map[string]any {
	var raw map[string]json.RawMessage
	must(0, json.Unmarshal(must(os.ReadFile(path)), &raw))
	out := map[string]any{}
	for _, v := range conf.Variables {
		desc := must(files.FindDescriptorByName(protoreflect.FullName(v.TypeName)))
		msg := dynamicpb.NewMessage(desc.(protoreflect.MessageDescriptor))
		// Omitted (non-structural) fields aren't declared, so the binding drops them.
		must(0, protojson.UnmarshalOptions{DiscardUnknown: true}.Unmarshal(raw[v.Name], msg))
		out[v.Name] = msg
	}
	return out
}

func eval(e *cel.Env, ast *cel.Ast, vars map[string]any) any {
	prg := must(e.Program(ast))
	out, _ := must2(prg.Eval(vars))
	return out.Value()
}

func must2[A, B any](a A, b B, err error) (A, B) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	return a, b
}

func main() {
	root := must(filepath.Abs(".."))
	gen := filepath.Join(root, "generated")
	var d demo
	readYAML(filepath.Join(root, "typedemo/gate_guard.yaml"), &d)
	conf := &env.Config{}
	readYAML(filepath.Join(gen, "env", d.Scope+".env.yaml"), conf)
	fds := &descriptorpb.FileDescriptorSet{}
	must(0, proto.Unmarshal(must(os.ReadFile(filepath.Join(gen, "types.binpb"))), fds))
	files := must(protodesc.NewFiles(fds))
	e := must(cel.NewEnv(cel.TypeDescs(fds), cel.FromConfig(conf, ext.ExtensionOptionFactory)))
	vars := activation(files, conf, filepath.Join(gen, "activation", d.Scope+".json"))
	failures := 0
	outDir := filepath.Join(gen, "checked", "go")
	must(0, os.MkdirAll(outDir, 0o755))
	for i, c := range d.Accept {
		ast, iss := e.Compile(c.Expr)
		if iss.Err() != nil {
			failures++
			fmt.Printf("BAD accept %q: %v\n", c.Expr, iss.Err())
			continue
		}
		got := eval(e, ast, vars)
		ok := got == c.Expect
		if !ok {
			failures++
		}
		fmt.Printf("%s accept %q -> %v\n", map[bool]string{true: "ok ", false: "BAD"}[ok], c.Expr, got)
		// The shipped form is a google.protobuf.Any holding a cel.expr.CheckedExpr, as cel-cpp writes it.
		// cel-go's v1alpha1 CheckedExpr has the same wire format as cel.expr.CheckedExpr.
		checked := must(proto.Marshal(must(cel.AstToCheckedExpr(ast))))
		wrapped := &anypb.Any{TypeUrl: "type.googleapis.com/cel.expr.CheckedExpr", Value: checked}
		must(0, os.WriteFile(filepath.Join(outDir, fmt.Sprintf("accept-%d.binpb", i)), must(proto.Marshal(wrapped)), 0o644))
	}
	for _, c := range d.Reject {
		if _, iss := e.Compile(c.Expr); iss.Err() != nil {
			fmt.Printf("ok  reject %q: %s\n", c.Expr, strings.SplitN(iss.Err().Error(), "\n", 2)[0])
			continue
		}
		failures++
		fmt.Printf("BAD reject %q type-checked; expected: %s\n", c.Expr, c.Why)
	}
	for _, dir := range must(filepath.Glob(filepath.Join(gen, "checked", "*"))) {
		if filepath.Base(dir) != "go" {
			failures += evalShipped(e, vars, d, dir)
		}
	}
	fmt.Printf("cel-go: %d failures\n", failures)
	if failures > 0 {
		os.Exit(1)
	}
}

// evalShipped evaluates the CheckedExprs another engine wrote, without parsing or checking them here.
func evalShipped(e *cel.Env, vars map[string]any, d demo, dir string) int {
	failures := 0
	for i, c := range d.Accept {
		data := must(os.ReadFile(filepath.Join(dir, fmt.Sprintf("accept-%d.binpb", i))))
		wrapped := &anypb.Any{}
		must(0, proto.Unmarshal(data, wrapped))
		checked := &exprpb.CheckedExpr{}
		must(0, proto.Unmarshal(wrapped.GetValue(), checked))
		got := eval(e, cel.CheckedExprToAst(checked), vars)
		ok := got == c.Expect
		if !ok {
			failures++
		}
		fmt.Printf("%s shipped from %s (%s) -> %v\n", map[bool]string{true: "ok ", false: "BAD"}[ok], filepath.Base(dir), wrapped.GetTypeUrl(), got)
	}
	return failures
}
