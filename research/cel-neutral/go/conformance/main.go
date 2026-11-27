// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Run the shared conformance suite on cel-go and write results/cel-go.jsonl.
//
// The environment comes from conformance/env.yaml through cel-go's own env Config reader.
package main

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/env"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/ext"
	"go.yaml.in/yaml/v3"
	"google.golang.org/protobuf/encoding/protojson"
)

type test struct {
	Name         string `json:"name"`
	Expr         string `json:"expr"`
	DisableCheck bool   `json:"disableCheck"`
}

type suiteFile struct {
	Name     string `json:"name"`
	Sections []struct {
		Name  string `json:"name"`
		Tests []test `json:"tests"`
	} `json:"sections"`
}

type row struct {
	File    string          `json:"file"`
	Section string          `json:"section"`
	Name    string          `json:"name"`
	Outcome string          `json:"outcome"`
	Value   json.RawMessage `json:"value,omitempty"`
	Message string          `json:"message,omitempty"`
}

func firstLine(s string) string { return strings.SplitN(s, "\n", 2)[0] }

func run(e *cel.Env, t test) row {
	ast, iss := e.Parse(t.Expr)
	if iss.Err() != nil {
		return row{Outcome: "parse_error", Message: firstLine(iss.Err().Error())}
	}
	if !t.DisableCheck {
		ast, iss = e.Check(ast)
		if iss.Err() != nil {
			return row{Outcome: "check_error", Message: firstLine(iss.Err().Error())}
		}
	}
	prg, err := e.Program(ast)
	if err != nil {
		return row{Outcome: "eval_error", Message: firstLine(err.Error())}
	}
	out, _, err := prg.Eval(cel.NoVars())
	if err != nil {
		return row{Outcome: "eval_error", Message: firstLine(err.Error())}
	}
	if types.IsError(out) {
		return row{Outcome: "eval_error", Message: firstLine(out.(error).Error())}
	}
	pb, err := cel.ValueAsProto(out)
	if err != nil {
		return row{Outcome: "value", Value: json.RawMessage(`{"unsupported":"` + out.Type().TypeName() + `"}`)}
	}
	js, _ := protojson.Marshal(pb)
	return row{Outcome: "value", Value: js}
}

func main() {
	_, self, _, _ := runtime.Caller(0)
	root := filepath.Join(filepath.Dir(self), "../../conformance")
	conf := &env.Config{}
	raw, err := os.ReadFile(filepath.Join(root, "env.yaml"))
	if err == nil {
		err = yaml.Unmarshal(raw, conf)
	}
	if err != nil {
		panic(err)
	}
	e, err := cel.NewEnv(cel.FromConfig(conf, ext.ExtensionOptionFactory))
	if err != nil {
		panic(err)
	}
	var suite []suiteFile
	raw, err = os.ReadFile(filepath.Join(root, "suite.json"))
	if err == nil {
		err = json.Unmarshal(raw, &suite)
	}
	if err != nil {
		panic(err)
	}
	f, err := os.Create(filepath.Join(root, "results/cel-go.jsonl"))
	if err != nil {
		panic(err)
	}
	defer f.Close()
	w := bufio.NewWriter(f)
	defer w.Flush()
	enc := json.NewEncoder(w)
	for _, file := range suite {
		for _, s := range file.Sections {
			for _, t := range s.Tests {
				r := run(e, t)
				r.File, r.Section, r.Name = file.Name, s.Name, t.Name
				_ = enc.Encode(r)
			}
		}
	}
}
