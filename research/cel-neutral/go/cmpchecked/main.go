// Compare two encodings of a shipped CheckedExpr as messages: proto.Equal ignores map order.
package main

import (
	"fmt"
	"os"

	exprpb "google.golang.org/genproto/googleapis/api/expr/v1alpha1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/anypb"
)

func load(path string) *exprpb.CheckedExpr {
	raw, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	a := &anypb.Any{}
	c := &exprpb.CheckedExpr{}
	if err := proto.Unmarshal(raw, a); err != nil {
		panic(err)
	}
	if err := proto.Unmarshal(a.Value, c); err != nil {
		panic(err)
	}
	return c
}

func main() {
	a, b := load(os.Args[1]), load(os.Args[2])
	fmt.Println("bytes equal:", string(mustMarshal(a)) == string(mustMarshal(b)), "messages equal:", proto.Equal(a, b))
}

func mustMarshal(m proto.Message) []byte {
	out, err := proto.MarshalOptions{Deterministic: true}.Marshal(m)
	if err != nil {
		panic(err)
	}
	return out
}
