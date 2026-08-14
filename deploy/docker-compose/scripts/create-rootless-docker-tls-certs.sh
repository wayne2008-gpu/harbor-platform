#!/usr/bin/env bash
set -euo pipefail

out_dir=${1:-.local/rootless-docker-certs}
server_name=${2:-host.docker.internal}
host_ip=${3:-127.0.0.1}
runtime_dir=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

mkdir -p "$out_dir/server" "$out_dir/client"
cert_dir=$(cd "$out_dir" && pwd -P)
chmod 700 "$cert_dir" "$cert_dir/server" "$cert_dir/client"

openssl genrsa -out "$cert_dir/ca-key.pem" 4096
openssl req -new -x509 -days 365 -key "$cert_dir/ca-key.pem"   -sha256 -out "$cert_dir/ca.pem" -subj "/CN=harbor-platform-rootless-docker-ca"

openssl genrsa -out "$cert_dir/server/key.pem" 4096
openssl req -subj "/CN=$server_name" -sha256 -new   -key "$cert_dir/server/key.pem" -out "$cert_dir/server/server.csr"
cat > "$cert_dir/server/extfile.cnf" <<EOF
subjectAltName = DNS:$server_name,IP:$host_ip,IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF
openssl x509 -req -days 365 -sha256   -in "$cert_dir/server/server.csr"   -CA "$cert_dir/ca.pem"   -CAkey "$cert_dir/ca-key.pem"   -CAcreateserial   -out "$cert_dir/server/cert.pem"   -extfile "$cert_dir/server/extfile.cnf"

openssl genrsa -out "$cert_dir/client/key.pem" 4096
openssl req -subj "/CN=harbor-runner" -new   -key "$cert_dir/client/key.pem" -out "$cert_dir/client/client.csr"
cat > "$cert_dir/client/extfile.cnf" <<EOF
extendedKeyUsage = clientAuth
EOF
openssl x509 -req -days 365 -sha256   -in "$cert_dir/client/client.csr"   -CA "$cert_dir/ca.pem"   -CAkey "$cert_dir/ca-key.pem"   -CAcreateserial   -out "$cert_dir/client/cert.pem"   -extfile "$cert_dir/client/extfile.cnf"

cp "$cert_dir/ca.pem" "$cert_dir/server/ca.pem"
cp "$cert_dir/ca.pem" "$cert_dir/client/ca.pem"
chmod 0400 "$cert_dir/ca-key.pem" "$cert_dir/server/key.pem" "$cert_dir/client/key.pem"
chmod 0444 "$cert_dir/ca.pem" "$cert_dir/server/ca.pem" "$cert_dir/server/cert.pem"   "$cert_dir/client/ca.pem" "$cert_dir/client/cert.pem"
rm -f "$cert_dir/server/server.csr" "$cert_dir/client/client.csr"

cat <<EOF
Generated Docker TLS certificates in $cert_dir

Start rootless dockerd with:
  dockerd-rootless.sh --host=tcp://0.0.0.0:2376 --host=unix://$runtime_dir/docker-rootless.sock --tlsverify --tlscacert=$cert_dir/server/ca.pem --tlscert=$cert_dir/server/cert.pem --tlskey=$cert_dir/server/key.pem

Use Compose with:
  export HARBOR_RUNNER_DOCKER_TLS_CERTS=$cert_dir
  docker compose -f compose.dev.yml -f compose.rootless-docker-tls.yml up --build
EOF
