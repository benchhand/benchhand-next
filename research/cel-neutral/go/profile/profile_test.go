// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

package profile

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const generated = "../../generated"

// The digest each language computes must equal the one gen/profile.py wrote.
func TestDigestMatchesGeneratedDigests(t *testing.T) {
	lines := strings.Split(strings.TrimSpace(string(mustRead(t, filepath.Join(generated, "profile", "digests.txt")))), "\n")
	for _, line := range lines {
		want, file, _ := strings.Cut(line, "  ")
		p, err := Load(generated, strings.TrimSuffix(file, ".profile.json"))
		if err != nil {
			t.Fatal(err)
		}
		if p.Digest != want {
			t.Errorf("%s: digest %s, digests.txt says %s", file, p.Digest, want)
		}
	}
}

// cel-go's extension factory accepts any numeric version; the adapter's inventory must refuse it.
func TestUnknownExtensionVersionIsRefused(t *testing.T) {
	dir := t.TempDir()
	raw := strings.Replace(string(mustRead(t, filepath.Join(generated, "profile", "gate_guard.profile.json"))),
		`"version": 4`, `"version": 99`, 1)
	if !strings.Contains(raw, `"version": 99`) {
		t.Fatal("fixture: strings version 4 not found in the manifest")
	}
	must(t, os.MkdirAll(filepath.Join(dir, "profile"), 0o755))
	must(t, os.WriteFile(filepath.Join(dir, "profile", "gate_guard.profile.json"), []byte(raw), 0o644))
	must(t, os.WriteFile(filepath.Join(dir, "types.binpb"), mustRead(t, filepath.Join(generated, "types.binpb")), 0o644))
	_, err := Load(dir, "gate_guard")
	if err == nil || !strings.Contains(err.Error(), "no strings version 99") {
		t.Fatalf("strings version 99 loaded; err = %v", err)
	}
}

// A CheckedExpr swapped under current bundle metadata must be refused by the payload hash.
func TestSubstitutedPayloadIsRefused(t *testing.T) {
	p, err := Load(generated, "gate_guard")
	if err != nil {
		t.Fatal(err)
	}
	ref := filepath.Join(generated, "checked", "cel-go-ref")
	b, err := LoadBundle(ref)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := p.VerifyBundle(ref, b, nil, true); err != nil {
		t.Fatalf("the reference bundle must verify without sources: %v", err)
	}
	dir := t.TempDir()
	for _, e := range b.Entries {
		must(t, os.WriteFile(filepath.Join(dir, e.File), mustRead(t, filepath.Join(ref, e.File)), 0o644))
	}
	must(t, os.WriteFile(filepath.Join(dir, "accept-0.binpb"), mustRead(t, filepath.Join(ref, "accept-1.binpb")), 0o644))
	_, err = p.VerifyBundle(dir, b, nil, true)
	if err == nil || !strings.Contains(err.Error(), "payload") {
		t.Fatalf("substituted payload accepted; err = %v", err)
	}
}

func mustRead(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}
