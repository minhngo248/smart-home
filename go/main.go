package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/cookiejar"
	"os"
	"strconv"
	"time"

	"github.com/joho/godotenv"
)

func main() {
	// Load variables from the repository root when running from this directory.
	if err := godotenv.Load("../.env"); err != nil {
		log.Println("[!] No ../.env file found, falling back to system environment variables")
	}

	deviceIP := os.Getenv("DEVICE_IP")
	tapoUser := os.Getenv("TAPO_USER")
	tapoPass := os.Getenv("TAPO_PASS")

	if deviceIP == "" || tapoUser == "" || tapoPass == "" {
		log.Fatalf("[-] Missing required environment variables (DEVICE_IP, TAPO_USER, or TAPO_PASS)")
	}

	userHash := sha1.Sum([]byte(tapoUser))
	passwordHash := sha1.Sum([]byte(tapoPass))
	authHash := sha256.Sum256(append(userHash[:], passwordHash[:]...))

	jar, err := cookiejar.New(nil)
	if err != nil {
		log.Fatalf("[-] Failed to create cookie jar: %v", err)
	}
	client := &http.Client{Timeout: 5 * time.Second, Jar: jar}

	localSeed, remoteSeed := phase1(client, deviceIP, authHash[:])
	session := phase2(client, deviceIP, jar, localSeed, remoteSeed, authHash[:])
	TurnOff(client, deviceIP, &session)
	VerifyLightState(client, deviceIP, &session)
}

type klapSession struct {
	key    []byte
	iv     []byte
	sigKey []byte
	seq    int32
}

func phase1(client *http.Client, deviceIP string, authHash []byte) ([]byte, []byte) {
	localSeed := make([]byte, 16)
	if _, err := rand.Read(localSeed); err != nil {
		log.Fatalf("[-] Failed to generate local seed: %v", err)
	}

	response := postBinary(client, fmt.Sprintf("http://%s/app/handshake1", deviceIP), localSeed)
	if response.status != http.StatusOK {
		log.Fatalf("[-] Phase 1 failed with status %d: %s", response.status, response.body)
	}
	if len(response.body) != 48 {
		log.Fatalf("[-] Invalid Phase 1 response length: %d bytes (expected 48)", len(response.body))
	}

	remoteSeed := response.body[:16]
	serverHash := response.body[16:]
	hashInput := append(append(append([]byte{}, localSeed...), remoteSeed...), authHash...)
	expectedHash := sha256.Sum256(hashInput)
	if !bytes.Equal(serverHash, expectedHash[:]) {
		log.Fatalf("[-] Phase 1 authentication failed: device hash does not match credentials")
	}

	fmt.Printf("[+] Phase 1 Success! Received remote_seed: %x\n", remoteSeed)
	return localSeed, remoteSeed
}

func phase2(client *http.Client, deviceIP string, jar http.CookieJar, localSeed, remoteSeed, authHash []byte) klapSession {
	hashInput := append(append(append([]byte{}, remoteSeed...), localSeed...), authHash...)
	clientHash := sha256.Sum256(hashInput)
	url := fmt.Sprintf("http://%s/app/handshake2", deviceIP)
	response := postBinary(client, url, clientHash[:])

	requestURL, err := http.NewRequest(http.MethodPost, url, nil)
	if err != nil {
		log.Fatalf("[-] Invalid Phase 2 URL: %v", err)
	}
	sessionID := ""
	for _, cookie := range jar.Cookies(requestURL.URL) {
		if cookie.Name == "TP_SESSIONID" {
			sessionID = cookie.Value
			break
		}
	}
	if response.status != http.StatusOK || sessionID == "" {
		log.Fatalf("[-] Phase 2 failed with status %d or missing TP_SESSIONID: %s", response.status, response.body)
	}

	key, iv, sigKey, seq := deriveKeys(localSeed, remoteSeed, authHash)
	fmt.Printf("[+] Phase 2 Success! Acquired TP_SESSIONID: %s\n", sessionID)
	return klapSession{key: key, iv: iv, sigKey: sigKey, seq: seq}
}

func TurnOff(client *http.Client, deviceIP string, session *klapSession) {
	sendLightState(client, deviceIP, session, map[string]int{
		"on_off":         0,
		"ignore_default": 1,
	})
}

func TurnOn(client *http.Client, deviceIP string, session *klapSession) {
	sendLightState(client, deviceIP, session, map[string]int{
		"on_off":         1,
		"ignore_default": 0,
	})
}

func ChangeBrightness(client *http.Client, deviceIP string, session *klapSession, brightness int) {
	if brightness < 1 || brightness > 100 {
		log.Fatalf("[-] Brightness must be between 1 and 100")
	}
	sendLightState(client, deviceIP, session, map[string]int{
		"on_off":         1,
		"brightness":     brightness,
		"ignore_default": 1,
	})
}

func ChangeColor(client *http.Client, deviceIP string, session *klapSession, hue, saturation, brightness int) {
	if hue < 0 || hue > 360 {
		log.Fatalf("[-] Hue must be between 0 and 360")
	}
	if saturation < 0 || saturation > 100 {
		log.Fatalf("[-] Saturation must be between 0 and 100")
	}
	if brightness < 1 || brightness > 100 {
		log.Fatalf("[-] Brightness must be between 1 and 100")
	}
	sendLightState(client, deviceIP, session, map[string]int{
		"on_off":         1,
		"hue":            hue,
		"saturation":     saturation,
		"brightness":     brightness,
		"color_temp":     0,
		"ignore_default": 1,
	})
}

func sendLightState(client *http.Client, deviceIP string, session *klapSession, state map[string]int) []byte {
	request := map[string]any{
		"smartlife.iot.smartbulb.lightingservice": map[string]any{
			"transition_light_state": state,
		},
	}
	plaintext, err := json.Marshal(request)
	if err != nil {
		log.Fatalf("[-] Failed to encode Phase 3 request: %v", err)
	}

	response := sendKlapRequest(client, deviceIP, session, plaintext)
	fmt.Printf("[+] Phase 3 Success! Light command accepted. Request: %s Response: %s\n", plaintext, response)
	return response
}

func sendKlapRequest(client *http.Client, deviceIP string, session *klapSession, plaintext []byte) []byte {
	session.seq++
	sequence := make([]byte, 4)
	binary.BigEndian.PutUint32(sequence, uint32(session.seq))
	ciphertext := encryptAES(session.key, append(append([]byte{}, session.iv...), sequence...), plaintext)
	signatureInput := append(append(append([]byte{}, session.sigKey...), sequence...), ciphertext...)
	signature := sha256.Sum256(signatureInput)
	payload := append(signature[:], ciphertext...)

	url := fmt.Sprintf("http://%s/app/request?seq=%d", deviceIP, session.seq)
	klapDebug("request seq=%d url=%s plaintext=%s", session.seq, url, plaintext)
	response := postBinary(client, url, payload)
	klapDebug("response seq=%d status=%d body_bytes=%d", session.seq, response.status, len(response.body))
	if response.status != http.StatusOK {
		log.Fatalf("[-] Phase 3 failed with status %d: %s", response.status, response.body)
	}
	if len(response.body) < 48 {
		log.Fatalf("[-] Invalid Phase 3 response length: %d bytes", len(response.body))
	}

	responseCiphertext := response.body[32:]
	responseSignatureInput := append(append(append([]byte{}, session.sigKey...), sequence...), responseCiphertext...)
	expectedSignature := sha256.Sum256(responseSignatureInput)
	if !bytes.Equal(response.body[:32], expectedSignature[:]) {
		log.Fatalf("[-] Phase 3 response signature verification failed")
	}
	responsePlaintext := decryptAES(session.key, append(append([]byte{}, session.iv...), sequence...), responseCiphertext)
	var responseValue map[string]any
	if err := json.Unmarshal(responsePlaintext, &responseValue); err != nil {
		log.Fatalf("[-] Invalid Phase 3 JSON response: %v", err)
	}
	if errorCode, ok := responseValue["error_code"].(float64); ok && errorCode != 0 {
		log.Fatalf("[-] Phase 3 device error: %v", errorCode)
	}
	klapDebug("response seq=%d plaintext=%s", session.seq, responsePlaintext)
	return responsePlaintext
}

func VerifyLightState(client *http.Client, deviceIP string, session *klapSession) {
	request := map[string]any{
		"system": map[string]any{
			"get_sysinfo": map[string]any{},
		},
	}
	plaintext, err := json.Marshal(request)
	if err != nil {
		log.Fatalf("[-] Failed to encode light-state request: %v", err)
	}
	responsePlaintext := sendKlapRequest(client, deviceIP, session, plaintext)

	var responseValue map[string]map[string]any
	if err := json.Unmarshal(responsePlaintext, &responseValue); err != nil {
		log.Fatalf("[-] Invalid light-state JSON response: %v", err)
	}
	system, ok := responseValue["system"]
	if !ok {
		log.Fatalf("[-] State response is missing system: %s", responsePlaintext)
	}
	sysInfo, ok := system["get_sysinfo"].(map[string]any)
	if !ok {
		log.Fatalf("[-] State response is missing get_sysinfo: %s", responsePlaintext)
	}
	state, ok := sysInfo["light_state"].(map[string]any)
	if !ok {
		log.Fatalf("[-] State response is missing light_state: %s", responsePlaintext)
	}
	onOff, ok := state["on_off"].(float64)
	if !ok {
		log.Fatalf("[-] State response is missing numeric on_off: %s", responsePlaintext)
	}
	fmt.Printf("[+] Verified bulb state: on_off=%d\n", int(onOff))
}

func klapDebug(format string, args ...any) {
	if enabled, _ := strconv.ParseBool(os.Getenv("KLAP_DEBUG")); enabled {
		fmt.Printf("[DEBUG] "+format+"\n", args...)
	}
}

type binaryResponse struct {
	status int
	body   []byte
}

func postBinary(client *http.Client, url string, payload []byte) binaryResponse {
	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		log.Fatalf("[-] Failed to create request: %v", err)
	}
	request.Header.Set("Content-Type", "application/octet-stream")
	response, err := client.Do(request)
	if err != nil {
		log.Fatalf("[-] Request failed: %v", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		log.Fatalf("[-] Failed to read response: %v", err)
	}
	return binaryResponse{status: response.StatusCode, body: body}
}

func deriveKeys(localSeed, remoteSeed, authHash []byte) (key, iv, sigKey []byte, seq int32) {
	keyHash := sha256.Sum256(append(append(append([]byte("lsk"), localSeed...), remoteSeed...), authHash...))
	ivHash := sha256.Sum256(append(append(append([]byte("iv"), localSeed...), remoteSeed...), authHash...))
	sigHash := sha256.Sum256(append(append(append([]byte("ldk"), localSeed...), remoteSeed...), authHash...))
	return keyHash[:16], ivHash[:12], sigHash[:28], int32(binary.BigEndian.Uint32(ivHash[28:]))
}

func encryptAES(key, iv, plaintext []byte) []byte {
	block, err := aes.NewCipher(key)
	if err != nil {
		log.Fatalf("[-] Failed to create AES cipher: %v", err)
	}
	padded := pkcs7Pad(plaintext, block.BlockSize())
	ciphertext := make([]byte, len(padded))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(ciphertext, padded)
	return ciphertext
}

func decryptAES(key, iv, ciphertext []byte) []byte {
	block, err := aes.NewCipher(key)
	if err != nil || len(ciphertext)%block.BlockSize() != 0 {
		log.Fatalf("[-] Invalid AES response")
	}
	plaintext := make([]byte, len(ciphertext))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(plaintext, ciphertext)
	return pkcs7Unpad(plaintext, block.BlockSize())
}

func pkcs7Pad(data []byte, blockSize int) []byte {
	padding := blockSize - len(data)%blockSize
	return append(append([]byte{}, data...), bytes.Repeat([]byte{byte(padding)}, padding)...)
}

func pkcs7Unpad(data []byte, blockSize int) []byte {
	if len(data) == 0 || len(data)%blockSize != 0 {
		log.Fatalf("[-] Invalid PKCS#7 response padding")
	}
	padding := int(data[len(data)-1])
	if padding == 0 || padding > blockSize || padding > len(data) || !bytes.Equal(data[len(data)-padding:], bytes.Repeat([]byte{byte(padding)}, padding)) {
		log.Fatalf("[-] Invalid PKCS#7 response padding")
	}
	return data[:len(data)-padding]
}
