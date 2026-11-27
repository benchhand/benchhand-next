// Package profile is the Go side of the environment profile: load a manifest, check it, and build the
// cel-go environment from it, plus the bundle.json that binds CheckedExprs to a profile, a checker and
// their exact payload bytes.
//
// The manifest (generated/profile/<name>.profile.json, written by gen/profile.py) is the only input. The
// profile digest is the SHA-256 of the manifest's RFC 8785 (JCS) encoding. A manifest holds only ASCII
// strings, integers, booleans, arrays and objects; for that subset JCS is sorted keys with no whitespace,
// which encoding/json gives for a map with HTML escaping off.
package profile

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strconv"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/env"
	"cel.dev/cel-go/ext"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/descriptorpb"
)

// Manifest is generated/profile/<name>.profile.json.
type Manifest struct {
	ManifestVersion int    `json:"manifest_version"`
	Name            string `json:"name"`
	DescriptorSet   struct {
		File   string `json:"file"`
		SHA256 string `json:"sha256"`
	} `json:"descriptor_set"`
	Container string `json:"container"`
	Variables []struct {
		Name string `json:"name"`
		Type string `json:"type"`
	} `json:"variables"`
	Extensions []struct {
		Name    string `json:"name"`
		Version int    `json:"version"`
	} `json:"extensions"`
	Options struct {
		CrossTypeNumericComparisons  bool `json:"cross_type_numeric_comparisons"`
		HomogeneousAggregateLiterals bool `json:"homogeneous_aggregate_literals"`
	} `json:"options"`
	CheckersOfRecord []Checker `json:"checkers_of_record"`
}

// Checker identifies the checker that wrote a bundle: an engine and its pinned version.
type Checker struct {
	Engine  string `json:"engine"`
	Version string `json:"version"`
}

// CelGoExtensions is the cel-go adapter's supported-version inventory. cel-go's extension factory
// passes any numeric version through to the extension without checking that it exists, so the adapter
// refuses every version outside this list itself. Each listed version was exercised here: by the shared
// suite, the typed demo or the policy compile.
var CelGoExtensions = map[string][]int{
	"strings":  {4},
	"optional": {2},
	"bindings": {0, 1},
	"math":     {1},
	"encoders": {0},
}

// Profile is a loaded manifest, its digest, and the descriptor set it names.
type Profile struct {
	Manifest      Manifest
	Digest        string
	DescriptorSet *descriptorpb.FileDescriptorSet
}

func sum(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

// Digest is the SHA-256 of the canonical JSON of a manifest's raw bytes.
func Digest(raw []byte) (string, error) {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return "", err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	return sum(bytes.TrimSuffix(buf.Bytes(), []byte("\n"))), nil
}

// Load reads and checks generated/profile/<name>.profile.json and the descriptor set it names.
func Load(generated, name string) (*Profile, error) {
	raw, err := os.ReadFile(filepath.Join(generated, "profile", name+".profile.json"))
	if err != nil {
		return nil, err
	}
	p := &Profile{}
	if err := json.Unmarshal(raw, &p.Manifest); err != nil {
		return nil, err
	}
	if p.Digest, err = Digest(raw); err != nil {
		return nil, err
	}
	fdsBytes, err := os.ReadFile(filepath.Join(generated, p.Manifest.DescriptorSet.File))
	if err != nil {
		return nil, err
	}
	if sum(fdsBytes) != p.Manifest.DescriptorSet.SHA256 {
		return nil, fmt.Errorf("%s: the descriptor set doesn't match the manifest's SHA-256", name)
	}
	for _, e := range p.Manifest.Extensions {
		if !slices.Contains(CelGoExtensions[e.Name], e.Version) {
			return nil, fmt.Errorf("%s: the cel-go adapter has no %s version %d", name, e.Name, e.Version)
		}
	}
	p.DescriptorSet = &descriptorpb.FileDescriptorSet{}
	return p, proto.Unmarshal(fdsBytes, p.DescriptorSet)
}

// EnvOptions are the cel-go options for the profile, and nothing else: the standard library, the
// descriptor set, the declared variables, each listed extension at its pinned version, and the options.
func (p *Profile) EnvOptions() []cel.EnvOption {
	m := p.Manifest
	conf := &env.Config{Name: m.Name, Container: m.Container}
	for _, v := range m.Variables {
		conf.Variables = append(conf.Variables, env.NewVariable(v.Name, env.NewTypeDesc(v.Type)))
	}
	for _, e := range m.Extensions {
		conf.Extensions = append(conf.Extensions, &env.Extension{Name: e.Name, Version: strconv.Itoa(e.Version)})
	}
	opts := []cel.EnvOption{
		cel.TypeDescs(p.DescriptorSet),
		cel.FromConfig(conf, ext.ExtensionOptionFactory),
		cel.CrossTypeNumericComparisons(m.Options.CrossTypeNumericComparisons),
	}
	if m.Options.HomogeneousAggregateLiterals {
		opts = append(opts, cel.HomogeneousAggregateLiterals())
	}
	return opts
}

// Bundle is the bundle.json beside a directory of CheckedExprs. Its identity is three things: the
// profile digest, the checker, and the SHA-256 of each entry's exact payload bytes.
type Bundle struct {
	ProfileSHA256 string  `json:"profile_sha256"`
	Checker       Checker `json:"checker"`
	Entries       []Entry `json:"entries"`
}

// Entry is one CheckedExpr file: the SHA-256 of its exact bytes, the SHA-256 of the source it was
// checked from, and the source file, if any.
type Entry struct {
	File          string `json:"file"`
	PayloadSHA256 string `json:"payload_sha256"`
	SourceSHA256  string `json:"source_sha256"`
	Source        string `json:"source,omitempty"`
}

// WriteBundle writes dir/bundle.json for the payload files already in dir and their sources.
func (p *Profile) WriteBundle(dir string, checker Checker, sources map[string]string, sourceFiles map[string]string) error {
	b := Bundle{ProfileSHA256: p.Digest, Checker: checker}
	for file, src := range sources {
		payload, err := os.ReadFile(filepath.Join(dir, file))
		if err != nil {
			return err
		}
		b.Entries = append(b.Entries, Entry{File: file, PayloadSHA256: sum(payload), SourceSHA256: sum([]byte(src)), Source: sourceFiles[file]})
	}
	sort.Slice(b.Entries, func(i, j int) bool { return b.Entries[i].File < b.Entries[j].File })
	out, err := json.MarshalIndent(b, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "bundle.json"), append(out, '\n'), 0o644)
}

// LoadBundle parses dir/bundle.json.
func LoadBundle(dir string) (Bundle, error) {
	var b Bundle
	raw, err := os.ReadFile(filepath.Join(dir, "bundle.json"))
	if err != nil {
		return b, fmt.Errorf("%s: no bundle.json, so the profile is unknown", filepath.Base(dir))
	}
	return b, json.Unmarshal(raw, &b)
}

// ReadBundle is VerifyBundle on dir/bundle.json, requiring a checker of record.
func (p *Profile) ReadBundle(dir string, sources map[string]string) (map[string][]byte, error) {
	b, err := LoadBundle(dir)
	if err != nil {
		return nil, err
	}
	return p.VerifyBundle(dir, b, sources, true)
}

// IsCheckerOfRecord reports whether the profile names the checker as one of record.
func (p *Profile) IsCheckerOfRecord(c Checker) bool {
	return slices.Contains(p.Manifest.CheckersOfRecord, c)
}

// VerifyBundle returns each entry's payload after checking, in order: the profile digest, the checker
// of record (when required), each payload's SHA-256, and each source's SHA-256 when sources is not nil.
// An evaluator that has only the bundle passes nil: the bundle's producer verified the sources when it
// checked them, and the host verifies them again at load, where it has them.
func (p *Profile) VerifyBundle(dir string, b Bundle, sources map[string]string, requireCheckerOfRecord bool) (map[string][]byte, error) {
	name := filepath.Base(dir)
	if b.ProfileSHA256 != p.Digest {
		return nil, fmt.Errorf("%s: checked in profile %.12s, not %.12s", name, b.ProfileSHA256, p.Digest)
	}
	if requireCheckerOfRecord && !p.IsCheckerOfRecord(b.Checker) {
		return nil, fmt.Errorf("%s: %s %s isn't a checker of record for this profile", name, b.Checker.Engine, b.Checker.Version)
	}
	out := map[string][]byte{}
	for _, e := range b.Entries {
		data, err := os.ReadFile(filepath.Join(dir, e.File))
		if err != nil {
			return nil, err
		}
		if sum(data) != e.PayloadSHA256 {
			return nil, fmt.Errorf("%s/%s: the payload isn't the one the checker shipped", name, e.File)
		}
		if src, ok := sources[e.File]; sources != nil && (!ok || sum([]byte(src)) != e.SourceSHA256) {
			return nil, fmt.Errorf("%s/%s: stale, the source changed since it was checked", name, e.File)
		}
		out[e.File] = data
	}
	return out, nil
}

// Record is one outcome in results/typed-demo/<engine>.json.
type Record struct {
	Engine string `json:"engine"`
	Kind   string `json:"kind"`
	Case   string `json:"case"`
	Writer string `json:"writer,omitempty"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
}

// WriteResults writes results/typed-demo/<name>.json under root.
func WriteResults(root, name string, records []Record) error {
	dir := filepath.Join(root, "results", "typed-demo")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	out, err := json.MarshalIndent(records, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, name+".json"), append(out, '\n'), 0o644)
}
