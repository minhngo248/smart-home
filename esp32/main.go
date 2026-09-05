package main

import (
	"context"
	"net"
	"time"

	mqtt "github.com/soypat/natiu-mqtt"
	"tinygo.org/x/drivers/netdev"
	nl "tinygo.org/x/drivers/netlink"
	link "tinygo.org/x/espradio/netlink"
)

// Set these via -ldflags="-X main.ssid=... -X main.password=..." at build/flash
// time, or replace with literal values in a separate gitignored config file.
var (
	ssid     string
	password string
)

const (
	mqttBroker = "192.168.1.10" // hardcoded IP - skips DNS resolution entirely
	mqttPort   = "30883"
	mqttTopic  = "/home/office/light"
	clientID   = "esp32-light"
)

func main() {
	esplink := &link.Esplink{}
	netdev.UseNetdev(esplink)

	connectWifi(esplink)

	runMQTTLoop()
}

// connectWifi retries the WiFi connection with a backoff delay between
// attempts. This matters because some routers/APs temporarily refuse new
// associations (WIFI_REASON_ASSOC_COMEBACK_TIME_TOO_LONG, error 208) as a
// rate-limiting measure - a single failed attempt does not mean the
// credentials are wrong, and retrying after a short wait often succeeds.
func connectWifi(esplink *link.Esplink) {
	attempt := 0
	for {
		attempt++
		println("Connecting to WiFi:", ssid, "(attempt", attempt, ")")
		err := esplink.NetConnect(&nl.ConnectParams{
			Ssid:       ssid,
			Passphrase: password,
		})
		if err == nil {
			println("Connected to WiFi.")
			return
		}
		println("wifi connect failed:", err.Error())
		time.Sleep(5 * time.Second)
	}
}

func runMQTTLoop() {
	server := net.JoinHostPort(mqttBroker, mqttPort)
	messages := []string{"on", "off"}
	decodeBuf := make([]byte, 1500) // allocate once, reuse across reconnects

	attempt := 0
	for {
		attempt++
		println("---- attempt", attempt, "----")
		println("Dialing", server)

		conn, err := net.Dial("tcp", server)
		if err != nil {
			println("TCP dial failed:", err.Error())
			time.Sleep(5 * time.Second)
			continue
		}
		println("TCP connected.")

		client := mqtt.NewClient(mqtt.ClientConfig{
			Decoder: mqtt.DecoderNoAlloc{UserBuffer: decodeBuf},
		})

		var connect mqtt.VariablesConnect
		connect.SetDefaultMQTT([]byte(clientID))

		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		err = client.Connect(ctx, conn, &connect)
		cancel()
		if err != nil {
			println("MQTT CONNECT failed:", err.Error())
			conn.Close()
			time.Sleep(5 * time.Second)
			continue
		}
		println("MQTT connected. Publishing to", mqttTopic)

		flags, err := mqtt.NewPublishFlags(mqtt.QoS0, false, false)
		if err != nil {
			println("Publish flags error:", err.Error())
			conn.Close()
			time.Sleep(5 * time.Second)
			continue
		}

		publishFailed := false
		var packetID uint16 = 1
		for i := 0; ; i++ {
			msg := messages[i%len(messages)]
			err = client.PublishPayload(flags, mqtt.VariablesPublish{
				TopicName:        []byte(mqttTopic),
				PacketIdentifier: packetID,
			}, []byte(msg))
			if err != nil {
				println("Publish failed:", err.Error())
				publishFailed = true
				break
			}
			println("Published:", msg)

			packetID++
			if packetID == 0 {
				packetID = 1 // wrap around, but never land on 0
			}

			time.Sleep(5 * time.Second)
		}

		conn.Close()
		if publishFailed {
			println("Connection dropped, reconnecting in 5s...")
			time.Sleep(5 * time.Second)
		}
	}
}
