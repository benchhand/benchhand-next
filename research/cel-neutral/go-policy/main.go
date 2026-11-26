// Compile a .celpolicy with cel-go's policy compiler and write the result as one CheckedExpr (in an Any),
// so the evaluators that read CheckedExprs can run a policy without a policy implementation of their own.
//
// Usage: go run . <policy.celpolicy> <out.binpb>
package main

import (
	"fmt"
	"os"
	"strings"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/ext"
	"cel.dev/cel-go/policy"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protodesc"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/known/anypb"
)

func must[T any](v T, err error) T {
	if err != nil {
		panic(err)
	}
	return v
}

func main() {
	src, out := os.Args[1], os.Args[2]
	fds := &descriptorpb.FileDescriptorSet{}
	if err := proto.Unmarshal(must(os.ReadFile("../generated/types.binpb")), fds); err != nil {
		panic(err)
	}
	files := must(protodesc.NewFiles(fds))
	env := must(cel.NewEnv(
		cel.TypeDescs(files),
		cel.OptionalTypes(),
		// cel.@block, which the composer uses for policy variables, is part of the bindings extension.
		ext.Bindings(ext.BindingsVersion(1)),
		cel.Variable("stage", cel.StringType),
		cel.Variable("iteration", cel.StringType),
		cel.Variable("part", cel.ObjectType("benchhand.contracts.record.part.Part")),
	))
	parser := must(policy.NewParser())
	p, iss := parser.Parse(policy.ByteSource(must(os.ReadFile(src)), src))
	if iss.Err() != nil {
		fmt.Fprintln(os.Stderr, iss.Err())
		os.Exit(1)
	}
	ast, iss := policy.Compile(env, p)
	if iss.Err() != nil {
		fmt.Fprintln(os.Stderr, iss.Err())
		os.Exit(1)
	}
	checked := must(cel.AstToCheckedExpr(ast))
	any := must(anypb.New(checked))
	any.TypeUrl = "type.googleapis.com/cel.expr.CheckedExpr"
	if err := os.WriteFile(out, must(proto.Marshal(any)), 0o644); err != nil {
		panic(err)
	}
	text := must(cel.AstToString(ast))
	fmt.Printf("output type %s\n%s\n", ast.OutputType(), strings.ReplaceAll(text, "\n", " "))
}
