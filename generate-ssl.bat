git @echo off
echo 🔐 Generating SSL certificates for development...

REM Create ssl directory
if not exist ssl mkdir ssl

REM Generate private key
openssl genrsa -out ssl\key.pem 2048

REM Generate certificate signing request
openssl req -new -key ssl\key.pem -out ssl\cert.csr -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

REM Generate self-signed certificate
openssl x509 -req -in ssl\cert.csr -signkey ssl\key.pem -out ssl\cert.pem -days 365

REM Clean up CSR
del ssl\cert.csr

echo ✅ SSL certificates generated successfully!
echo 📁 Certificates saved in ssl\ directory
echo 🔒 Key file: ssl\key.pem
echo 📜 Certificate file: ssl\cert.pem
echo.
echo ⚠️  Note: These are self-signed certificates for development only.
echo    For production, use proper SSL certificates from a trusted CA. 