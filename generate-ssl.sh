#!/bin/bash

# Generate SSL certificates for development
# This script creates self-signed certificates for local development

echo "🔐 Generating SSL certificates for development..."

# Create ssl directory
mkdir -p ssl

# Generate private key
openssl genrsa -out ssl/key.pem 2048

# Generate certificate signing request
openssl req -new -key ssl/key.pem -out ssl/cert.csr -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Generate self-signed certificate
openssl x509 -req -in ssl/cert.csr -signkey ssl/key.pem -out ssl/cert.pem -days 365

# Set proper permissions
chmod 600 ssl/key.pem
chmod 644 ssl/cert.pem

# Clean up CSR
rm ssl/cert.csr

echo "✅ SSL certificates generated successfully!"
echo "📁 Certificates saved in ssl/ directory"
echo "🔒 Key file: ssl/key.pem"
echo "📜 Certificate file: ssl/cert.pem"
echo ""
echo "⚠️  Note: These are self-signed certificates for development only."
echo "   For production, use proper SSL certificates from a trusted CA." 