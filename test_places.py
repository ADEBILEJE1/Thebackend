import requests

def test_google_places_api(api_key):
    # Test with a simple place search
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        'query': 'restaurant',
        'key': api_key
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if response.status_code == 200 and data.get('status') == 'OK':
            print(f"✓ API Key Valid - Found {len(data.get('results', []))} results")
            return True
        else:
            print(f"✗ API Error: {data.get('error_message', data.get('status'))}")
            return False
            
    except Exception as e:
        print(f"✗ Request Failed: {e}")
        return False

# Test the key
api_key = "AIzaSyA7KmI73oQc5NrnIMsoGUe_BkiUOlzf1t0"
test_google_places_api(api_key)