package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

func main() {
	// Load variables from .env file in the current directory
	if err := godotenv.Load(); err != nil {
		log.Println("[!] No .env file found, falling back to system environment variables")
	}

	deviceIP := os.Getenv("DEVICE_IP")
	tapoUser := os.Getenv("TAPO_USER")
	tapoPass := os.Getenv("TAPO_PASS")

	if deviceIP == "" || tapoUser == "" || tapoPass == "" {
		log.Fatalf("[-] Missing required environment variables (DEVICE_IP, TAPO_USER, or TAPO_PASS)")
	}

	client := &http.Client{Timeout: 5 * time.Second}

	// ==========================================
	// PHASE 1: Send local_seed1, receive 48 bytes
	// ==========================================
	localSeed1 := make([]byte, 16)
	rand.Read(localSeed1)

	url1 := fmt.Sprintf("http://%s/app/handshake1", deviceIP)
	req1, _ := http.NewRequest("POST", url1, bytes.NewReader(localSeed1))
	req1.Header.Set("Content-Type", "application/octet-stream")

	fmt.Println("[*] Executing Phase 1 (/app/handshake1)...")
	resp1, err := client.Do(req1)
	if err != nil {
		log.Fatalf("[-] Phase 1 connection failed: %v", err)
	}
	defer resp1.Body.Close()

	resp1Bytes, err := io.ReadAll(resp1.Body)
	if err != nil || resp1.StatusCode != 200 {
		log.Fatalf("[-] Phase 1 failed with status %d: %s", resp1.StatusCode, string(resp1Bytes))
	}

	if len(resp1Bytes) < 48 {
		log.Fatalf("[-] Invalid Phase 1 response length: %d bytes (expected 48)", len(resp1Bytes))
	}

	// Parse Phase 1 Binary Response (48 bytes total)
	// Bytes 0-15: local_seed2
	// Bytes 16-47: device_hash / signature
	localSeed2 := resp1Bytes[:16]
	fmt.Printf("[+] Phase 1 Success! Received local_seed2: %x\n", localSeed2)

	// ==========================================
	// KEY DERIVATION
	// ==========================================
	userLower := strings.ToLower(tapoUser)
	uHash := sha256.Sum256([]byte(userLower))
	pHash := sha256.Sum256([]byte(tapoPass))

	combined := sha256.Sum256([]byte(hex.EncodeToString(uHash[:]) + hex.EncodeToString(pHash[:])))
	authHash := hex.EncodeToString(combined[:])

	// Derive AES Key, IV, and SigKey
	key, iv, sigKey := DeriveKeys(localSeed1, localSeed2, authHash)

	// ==========================================
	// # PHASE 2: Encrypt local_seed2 and authenticate
	// ==========================================
	block, err := aes.NewCipher(sigKey)
	if err != nil {
		log.Fatalf("[-] Failed to create cipher for handshake2: %v", err)
	}

	mode := cipher.NewCBCEncrypter(block, sigKey[:16])
	encryptedSeed2 := make([]byte, len(localSeed2))
	mode.CryptBlocks(encryptedSeed2, localSeed2)

	url2 := fmt.Sprintf("http://%s/app/handshake2", deviceIP)
	req2, _ := http.NewRequest("POST", url2, bytes.NewReader(encryptedSeed2))
	req2.Header.Set("Content-Type", "application/octet-stream")

	fmt.Println("[*] Executing Phase 2 (/app/handshake2)...")
	resp2, err := client.Do(req2)
	if err != nil {
		log.Fatalf("[-] Phase 2 connection failed: %v", err)
	}
	defer resp2.Body.Close()

	// Extract Session Cookie
	var sessionID string
	for _, cookie := range resp2.Cookies() {
		if cookie.Name == "TP_SESSIONID" {
			sessionID = cookie.Value
			break
		}
	}

	if resp2.StatusCode != 200 || sessionID == "" {
		resp2Body, _ := io.ReadAll(resp2.Body)
		log.Fatalf("[-] Phase 2 failed with status %d: %s", resp2.StatusCode, string(resp2Body))
	}

	fmt.Printf("[+] Phase 2 Success! Acquired TP_SESSIONID: %s\n", sessionID)
	fmt.Printf("[+] Derived Session AES Key: %x\n", key)
	fmt.Printf("[+] Derived Session IV     : %x\n", iv)
}

func DeriveKeys(localSeed1, localSeed2 []byte, authHash string) (key, iv, sigKey []byte) {
	keyBuf := append([]byte("lsk"), localSeed1...)
	keyBuf = append(keyBuf, localSeed2...)
	keyBuf = append(keyBuf, []byte(authHash)...)
	keyHash := sha256.Sum256(keyBuf)

	ivBuf := append([]byte("iv"), localSeed1...)
	ivBuf = append(ivBuf, localSeed2...)
	ivBuf = append(ivBuf, []byte(authHash)...)
	ivHash := sha256.Sum256(ivBuf)

	sigBuf := append([]byte("ldk"), localSeed1...)
	sigBuf = append(sigBuf, localSeed2...)
	sigBuf = append(sigBuf, []byte(authHash)...)
	sigHash := md5.Sum(sigBuf)

	return keyHash[:16], ivHash[:16], sigHash[:]
}
