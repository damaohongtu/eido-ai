package protocol

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"testing"
)

func TestNativeMessageRoundTrip(t *testing.T) {
	input := Request{Protocol: 1, Command: "launch", Workspace: "/tmp/project", PreferredPort: 4096}
	payload, _ := json.Marshal(input)
	buffer := new(bytes.Buffer)
	_ = binary.Write(buffer, binary.LittleEndian, uint32(len(payload)))
	_, _ = buffer.Write(payload)

	got, err := ReadRequest(buffer)
	if err != nil {
		t.Fatalf("ReadRequest returned error: %v", err)
	}
	if got.Command != input.Command || got.Workspace != input.Workspace || got.PreferredPort != 4096 {
		t.Fatalf("unexpected request: %#v", got)
	}
}

func TestReadRequestRejectsOversizedMessage(t *testing.T) {
	buffer := new(bytes.Buffer)
	_ = binary.Write(buffer, binary.LittleEndian, uint32(MaxMessageSize+1))
	if _, err := ReadRequest(buffer); err == nil {
		t.Fatal("expected oversized message to be rejected")
	}
}

func TestWriteResponseUsesFramedJSON(t *testing.T) {
	buffer := new(bytes.Buffer)
	if err := WriteResponse(buffer, map[string]any{"ok": true}); err != nil {
		t.Fatalf("WriteResponse returned error: %v", err)
	}
	var size uint32
	_ = binary.Read(buffer, binary.LittleEndian, &size)
	if int(size) != buffer.Len() {
		t.Fatalf("frame size %d does not match payload %d", size, buffer.Len())
	}
}
