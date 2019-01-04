client_id="ABCDEF1234567890"
secret="ABCDEF1234567890"

if [[ "$1" == "--sandbox" ]]; then
    url="https://api.sandbox.paypal.com/v1/oauth2/token"
else
    url="https://api.paypal.com/v1/oauth2/token"
fi

echo "Using URL Endpoint: $url"

curl -v $url\
     -H "Accept: application/json" \
     -H "Accept-Language: en_US" \
     -u "$client_id:$secret" \
     -d "grant_type=client_credentials"
echo
