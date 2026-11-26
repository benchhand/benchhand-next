// celcheck is the reference checker: cel-go with exactly the profile manifest's environment, built by
// go/profile with explicit options and nothing appended (unlike tools/compiler, whose NewCompiler always
// adds the latest optional and bindings extensions). It is the same cel-go version as the conformance
// oracle, pinned once in go/go.mod.
//
//	go run ./celcheck rules <profile> <rules.yaml>   check accept, reject and profile cases; write a bundle
//	go run ./celcheck policy <profile> <file.celpolicy> <name>   compile a policy into its profile's bundle
//
// `rules` writes generated/checked/cel-go-ref/ and results/typed-demo/celcheck.json. It fails when an
// accept case doesn't check, a reject case checks, or a profile case that uses an excluded function or
// syntax checks. `policy` writes generated/checked-policy/<profile>/, bound to the policy's source digest.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"celneutral/go/profile"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/policy"
	"go.yaml.in/yaml/v3"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/anypb"
)

// Version is the pinned cel-go module version, recorded in every bundle it writes.
const Version = "cel.dev/cel-go v0.33.4"

type rule struct {
	Expr    string `yaml:"expr"`
	Why     string `yaml:"why"`
	Feature string `yaml:"feature"`
	Refuse  bool   `yaml:"refuse"`
}

type rules struct {
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

func firstLine(err error) string { return strings.SplitN(err.Error(), "\n", 2)[0] }

func checker() profile.Checker {
	return profile.Checker{Engine: "celcheck", Version: Version}
}

func writeChecked(path string, ast *cel.Ast) {
	a := must(anypb.New(must(cel.AstToCheckedExpr(ast))))
	a.TypeUrl = "type.googleapis.com/cel.expr.CheckedExpr"
	must(0, os.WriteFile(path, must(proto.Marshal(a)), 0o644))
}

func checkRules(root string, p *profile.Profile, e *cel.Env, src string) []profile.Record {
	var rs rules
	must(0, yaml.Unmarshal(must(os.ReadFile(src)), &rs))
	out := filepath.Join(root, "generated", "checked", "cel-go-ref")
	must(0, os.MkdirAll(out, 0o755))
	var records []profile.Record
	add := func(kind, c string, ok bool, detail string) {
		records = append(records, profile.Record{Engine: "celcheck", Kind: kind, Case: c, OK: ok, Detail: detail})
		fmt.Printf("%s %s %q: %s\n", map[bool]string{true: "ok ", false: "BAD"}[ok], kind, c, detail)
	}
	sources := map[string]string{}
	for i, r := range rs.Accept {
		ast, iss := e.Compile(r.Expr)
		if iss.Err() != nil {
			add("accept", r.Expr, false, firstLine(iss.Err()))
			continue
		}
		name := fmt.Sprintf("accept-%d.binpb", i)
		writeChecked(filepath.Join(out, name), ast)
		sources[name] = r.Expr
		add("accept", r.Expr, true, "checked: "+ast.OutputType().String())
	}
	for _, r := range rs.Reject {
		_, iss := e.Compile(r.Expr)
		add("reject", r.Expr, iss.Err() != nil, fmt.Sprint(r.Why, ": ", iss.Err()))
	}
	for _, r := range rs.Profile {
		_, iss := e.Compile(r.Expr)
		detail := r.Feature + ": checked"
		if iss.Err() != nil {
			detail = r.Feature + ": " + firstLine(iss.Err())
		}
		add("profile", r.Expr, (iss.Err() != nil) == r.Refuse, detail)
	}
	must(0, p.WriteBundle(out, checker(), sources, nil))
	return records
}

func compilePolicy(root string, p *profile.Profile, e *cel.Env, src, name string) error {
	source := must(os.ReadFile(src))
	parsed, iss := must(policy.NewParser()).Parse(policy.ByteSource(source, src))
	if iss.Err() != nil {
		return iss.Err()
	}
	if err := restrictedProfile(parsed); err != nil {
		return fmt.Errorf("%s: %w", src, err)
	}
	ast, iss := policy.Compile(e, parsed)
	if iss.Err() != nil {
		return iss.Err()
	}
	dir := filepath.Join(root, "generated", "checked-policy", p.Manifest.Name)
	must(0, os.MkdirAll(dir, 0o755))
	file := name + ".binpb"
	writeChecked(filepath.Join(dir, file), ast)
	rel := must(filepath.Rel(root, must(filepath.Abs(src))))
	must(0, p.WriteBundle(dir, checker(), map[string]string{file: string(source)}, map[string]string{file: rel}))
	fmt.Printf("output type %s\n%s\n", ast.OutputType(), strings.ReplaceAll(must(cel.AstToString(ast)), "\n", " "))
	return nil
}

// restrictedProfile refuses what the supported policy profile excludes, before the compiler runs: a
// nested rule, policy variables, and a match with no unconditional last choice (its output would be an
// optional, so no match wouldn't mean UNKNOWN and the evaluator would need the optional extension).
// The profile with bindings in its manifest is the one exception for variables, kept to show the
// cel.@block form.
func restrictedProfile(p *policy.Policy) error {
	r := p.Rule()
	if len(r.Variables()) > 0 && !strings.HasSuffix(os.Args[2], "_bindings") {
		return fmt.Errorf("restricted profile: policy variables need cel.@block in every evaluator")
	}
	matches := r.Matches()
	for _, m := range matches {
		if m.HasRule() {
			return fmt.Errorf("restricted profile: nested rules aren't supported")
		}
	}
	if len(matches) == 0 || matches[len(matches)-1].Condition().Value != "true" && matches[len(matches)-1].Condition().Value != "" {
		return fmt.Errorf("restricted profile: the last choice must be unconditional, so no match is an explicit output")
	}
	return nil
}

func main() {
	if len(os.Args) < 4 {
		fmt.Fprintln(os.Stderr, "usage: celcheck rules <profile> <rules.yaml> | policy <profile> <file> <name>")
		os.Exit(2)
	}
	root := must(filepath.Abs(".."))
	p := must(profile.Load(filepath.Join(root, "generated"), os.Args[2]))
	e := must(cel.NewEnv(p.EnvOptions()...))
	switch os.Args[1] {
	case "rules":
		records := checkRules(root, p, e, os.Args[3])
		must(0, profile.WriteResults(root, "celcheck", records))
		for _, r := range records {
			if !r.OK {
				os.Exit(1)
			}
		}
	case "policy":
		if err := compilePolicy(root, p, e, os.Args[3], os.Args[4]); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	default:
		fmt.Fprintln(os.Stderr, "unknown command", os.Args[1])
		os.Exit(2)
	}
}
