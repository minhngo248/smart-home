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

	backoffInitial = 5 * time.Second
	backoffFactor  = 2
	maxRetries     = 4
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
	for attempt := 1; attempt <= maxRetries; attempt++ {
		println("Connecting to WiFi:", ssid, "(attempt", attempt, ")")
		err := esplink.NetConnect(&nl.ConnectParams{
			Ssid:       ssid,
			Passphrase: password,
		})
		if err == nil {
			addr, addrErr := esplink.Addr()
			if addrErr != nil {
				println("Connected to WiFi, but failed to read IP:", addrErr.Error())
			} else {
				println("Connected to WiFi. IP:", addr.String())
			}
			return
		}
		println("wifi connect failed:", err.Error())
		if attempt < maxRetries {
			time.Sleep(backoffDelay(attempt))
		}
	}
	panic("WiFi connection failed after maximum retries")
}

func runMQTTLoop() {
	server := net.JoinHostPort(mqttBroker, mqttPort)
	messages := []string{"on", "off"}
	decodeBuf := make([]byte, 1500) // allocate once, reuse across reconnects

	event := 0
	for {
		event++
		msg := messages[(event-1)%len(messages)]
		published := false
		for attempt := 1; attempt <= maxRetries; attempt++ {
			println("---- event", event, "attempt", attempt, "----")
			if err := publishMQTT(server, msg, decodeBuf); err == nil {
				published = true
				break
			} else {
				println("MQTT event failed:", err.Error())
			}
			if attempt < maxRetries {
				time.Sleep(backoffDelay(attempt))
			}
		}
		if !published {
			panic("MQTT event failed after maximum retries")
		}
		println("Waiting 5 minutes before the next event.")
		time.Sleep(5 * time.Minute)
	}
}

func backoffDelay(attempt int) time.Duration {
	delay := backoffInitial
	for i := 1; i < attempt; i++ {
		delay *= backoffFactor
	}
	return delay
}

func publishMQTT(server, msg string, decodeBuf []byte) error {
	println("Dialing", server)
	conn, err := net.Dial("tcp", server)
	if err != nil {
		return err
	}
	defer conn.Close()
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
		return err
	}
	println("MQTT connected. Publishing to", mqttTopic)

	flags, err := mqtt.NewPublishFlags(mqtt.QoS0, false, false)
	if err != nil {
		return err
	}

	err = client.PublishPayload(flags, mqtt.VariablesPublish{
		TopicName:        []byte(mqttTopic),
		PacketIdentifier: 1,
	}, []byte(msg))
	if err != nil {
		return err
	}
	println("Published:", msg)
	return nil
}
