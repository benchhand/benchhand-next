// The typed demo through cel-go's tools/compiler package: the env YAML and the descriptor set are loaded by
// cel-go's own file options (EnvironmentFile, TypeDescriptorSetFile), with no adapter code. Each accepted
// rule is written as a CheckedExpr to generated/checked/cel-go-tools/, where the other engines' demos pick
// it up; each rejected rule must fail. This is the library route to a reference checker in CI.
//
// Usage (from research/cel-neutral/go-policy): go run ./compilerfile
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/tools/compiler"
	"go.yaml.in/yaml/v3"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/anypb"
)

type demo struct {
	Scope  string `yaml:"scope"`
	Accept []struct {
		Expr string `yaml:"expr"`
	} `yaml:"accept"`
	Reject []struct {
		Expr string `yaml:"expr"`
		Why  string `yaml:"why"`
	} `yaml:"reject"`
}

func must[T any](v T, err error) T {
	if err != nil {
		panic(err)
	}
	return v
}

func main() {
	var d demo
	if err := yaml.Unmarshal(must(os.ReadFile("../typedemo/gate_guard.yaml")), &d); err != nil {
		panic(err)
	}
	// TypeDescriptorSetFile infers the format from the extension and accepts .binarypb, .fds or .pb, not
	// the .binpb that buf writes, so the descriptor set is copied under an accepted name.
	fds := filepath.Join(os.TempDir(), "cel-neutral-types.fds")
	if err := os.WriteFile(fds, must(os.ReadFile("../generated/types.binpb")), 0o644); err != nil {
		panic(err)
	}
	defer os.Remove(fds)
	c := must(compiler.NewCompiler(
		compiler.TypeDescriptorSetFile(fds),
		compiler.EnvironmentFile("../generated/env/"+d.Scope+".env.yaml"),
	))
	out := "../generated/checked/cel-go-tools"
	if err := os.MkdirAll(out, 0o755); err != nil {
		panic(err)
	}
	failures := 0
	for i, r := range d.Accept {
		ast, _, err := (&compiler.RawExpression{Value: r.Expr}).CreateAST(c)
		if err != nil {
			failures++
			fmt.Printf("BAD accept %q: %v\n", r.Expr, err)
			continue
		}
		checked := must(cel.AstToCheckedExpr(ast))
		a := must(anypb.New(checked))
		a.TypeUrl = "type.googleapis.com/cel.expr.CheckedExpr"
		if err := os.WriteFile(fmt.Sprintf("%s/accept-%d.binpb", out, i), must(proto.Marshal(a)), 0o644); err != nil {
			panic(err)
		}
		fmt.Printf("ok  accept %q -> %s\n", r.Expr, ast.OutputType())
	}
	for _, r := range d.Reject {
		if _, _, err := (&compiler.RawExpression{Value: r.Expr}).CreateAST(c); err != nil {
			fmt.Printf("ok  reject %q: %s\n", r.Expr, strings.SplitN(err.Error(), "\n", 2)[0])
			continue
		}
		failures++
		fmt.Printf("BAD reject %q type-checked; expected: %s\n", r.Expr, r.Why)
	}
	fmt.Printf("cel-go tools/compiler: %d failures\n", failures)
	if failures > 0 {
		os.Exit(1)
	}
}
