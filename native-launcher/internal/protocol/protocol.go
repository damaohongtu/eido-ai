package protocol

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const MaxMessageSize = 1024 * 1024

type Request struct {
	Protocol          int    `json:"protocol"`
	Command           string `json:"command"`
	InitialDirectory  string `json:"initialDirectory,omitempty"`
	DirectoryName     string `json:"directoryName,omitempty"`
	Workspace         string `json:"workspace,omitempty"`
	Hostname          string `json:"hostname,omitempty"`
	PreferredPort     int    `json:"preferredPort,omitempty"`
	Username          string `json:"username,omitempty"`
	Password          string `json:"password,omitempty"`
	AllowPortFallback bool   `json:"allowPortFallback,omitempty"`
	Endpoint          string `json:"endpoint,omitempty"`
}

func ReadRequest(reader io.Reader) (Request, error) {
	var size uint32
	if err := binary.Read(reader, binary.LittleEndian, &size); err != nil {
		return Request{}, fmt.Errorf("read message length: %w", err)
	}
	if size == 0 || size > MaxMessageSize {
		return Request{}, errors.New("message size is outside the allowed range")
	}
	payload := make([]byte, size)
	if _, err := io.ReadFull(reader, payload); err != nil {
		return Request{}, fmt.Errorf("read message payload: %w", err)
	}
	var request Request
	if err := json.Unmarshal(payload, &request); err != nil {
		return Request{}, fmt.Errorf("decode request: %w", err)
	}
	return request, nil
}

func WriteResponse(writer io.Writer, response any) error {
	payload, err := json.Marshal(response)
	if err != nil {
		return fmt.Errorf("encode response: %w", err)
	}
	if len(payload) > MaxMessageSize {
		return errors.New("response exceeds maximum message size")
	}
	if err := binary.Write(writer, binary.LittleEndian, uint32(len(payload))); err != nil {
		return fmt.Errorf("write response length: %w", err)
	}
	if _, err := writer.Write(payload); err != nil {
		return fmt.Errorf("write response payload: %w", err)
	}
	return nil
}
