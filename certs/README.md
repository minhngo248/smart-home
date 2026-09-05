# Certs
```bash
# Need custom CA

# For MQTT broker cert
openssl req -new \
  -newkey rsa:2048 \
  -nodes \
  -keyout ./certs/mosquitto/tls.key \
  -out ./certs/mosquitto/tls.csr \
  -subj "/C=US/ST=Home/L=Home/O=Minh Home Lab/OU=Infrastructure/CN=mosquitto-mqtts.mosquitto.svc.cluster.local"

openssl x509 -req \
  -in ./certs/mosquitto/tls.csr \
  -CA ./certs/ca.crt \
  -CAkey ./certs/ca.key \
  -CAcreateserial \
  -out ./certs/mosquitto/tls.crt \
  -days 825 \
  -sha256 \
  -extfile ./certs/mosquitto/local-pi.ext
```