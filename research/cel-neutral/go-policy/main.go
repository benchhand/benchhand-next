// Compile a .celpolicy with cel-go's policy compiler and write one CheckedExpr (in an Any) into the bundle
// of the profile it was compiled in, generated/checked-policy/<profile>/, with a bundle.json that names the
// profile digest and the SHA-256 of the policy source. The environment comes from the profile manifest.
//
// Usage: go run . <profile> <policy.celpolicy> <out name>
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/env"
	"cel.dev/cel-go/ext"
	"cel.dev/cel-go/policy"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/descriptorpb"
	"google.golang.org/protobuf/types/known/anypb"
)

type manifest struct {
	Name          string `json:"name"`
	DescriptorSet struct {
		File   string `json:"file"`
		SHA256 string `json:"sha256"`
	} `json:"descriptor_set"`
	Variables []struct {
		Name string `json:"name"`
		Type string `json:"type"`
	} `json:"variables"`
	Extensions []struct {
		Name    string `json:"name"`
		Version int    `json:"version"`
	} `json:"extensions"`
	Options struct {
		CrossTypeNumericComparisons bool `json:"cross_type_numeric_comparisons"`
	} `json:"options"`
}

func must[T any](v T, err error) T {
	if err != nil {
		panic(err)
	}
	return v
}

func sum(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

// digest is the SHA-256 of the manifest's JCS form (sorted keys, no whitespace, for its ASCII subset).
func digest(raw []byte) string {
	var v any
	must(0, json.Unmarshal(raw, &v))
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	must(0, enc.Encode(v))
	return sum(bytes.TrimSuffix(buf.Bytes(), []byte("\n")))
}

func main() {
	profileName, src, outName := os.Args[1], os.Args[2], os.Args[3]
	raw := must(os.ReadFile(filepath.Join("../generated/profile", profileName+".profile.json")))
	var m manifest
	must(0, json.Unmarshal(raw, &m))
	fdsBytes := must(os.ReadFile(filepath.Join("../generated", m.DescriptorSet.File)))
	if sum(fdsBytes) != m.DescriptorSet.SHA256 {
		panic("the descriptor set doesn't match the manifest")
	}
	fds := &descriptorpb.FileDescriptorSet{}
	must(0, proto.Unmarshal(fdsBytes, fds))
	conf := &env.Config{Name: m.Name}
	for _, v := range m.Variables {
		conf.Variables = append(conf.Variables, env.NewVariable(v.Name, env.NewTypeDesc(v.Type)))
	}
	for _, e := range m.Extensions {
		conf.Extensions = append(conf.Extensions, &env.Extension{Name: e.Name, Version: strconv.Itoa(e.Version)})
	}
	e := must(cel.NewEnv(cel.TypeDescs(fds), cel.FromConfig(conf, ext.ExtensionOptionFactory),
		cel.CrossTypeNumericComparisons(m.Options.CrossTypeNumericComparisons)))
	source := must(os.ReadFile(src))
	p, iss := must(policy.NewParser()).Parse(policy.ByteSource(source, src))
	if iss.Err() != nil {
		fmt.Fprintln(os.Stderr, iss.Err())
		os.Exit(1)
	}
	ast, iss := policy.Compile(e, p)
	if iss.Err() != nil {
		fmt.Fprintln(os.Stderr, iss.Err())
		os.Exit(1)
	}
	a := must(anypb.New(must(cel.AstToCheckedExpr(ast))))
	a.TypeUrl = "type.googleapis.com/cel.expr.CheckedExpr"
	dir := filepath.Join("../generated/checked-policy", profileName)
	must(0, os.MkdirAll(dir, 0o755))
	file := outName + ".binpb"
	must(0, os.WriteFile(filepath.Join(dir, file), must(proto.Marshal(a)), 0o644))
	rel := must(filepath.Rel(must(filepath.Abs("..")), must(filepath.Abs(src))))
	bundle := map[string]any{
		"profile_sha256": digest(raw),
		"checker":        map[string]string{"engine": "cel-go policy", "version": "0.33.4"},
		"entries":        []map[string]string{{"file": file, "source_sha256": sum(source), "source": rel}},
	}
	must(0, os.WriteFile(filepath.Join(dir, "bundle.json"), append(must(json.MarshalIndent(bundle, "", " ")), '\n'), 0o644))
	fmt.Printf("output type %s\n%s\n", ast.OutputType(), strings.ReplaceAll(must(cel.AstToString(ast)), "\n", " "))
}
