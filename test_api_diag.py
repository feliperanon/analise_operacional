import requests

BASE_URL = "http://127.0.0.1:8000"
SECTOR_ID = 1

def test_routes():
    print(f"Testando rotas para setor {SECTOR_ID}...\n")
    
    # 1. Tentar GET para confirmar que setor existe
    print(f"1. GET /api/smart-flow/sectors?shift=Manhã")
    try:
        r = requests.get(f"{BASE_URL}/api/smart-flow/sectors?shift=Manhã")
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            sectors = r.json().get('sectors', [])
            target = next((s for s in sectors if s['id'] == SECTOR_ID), None)
            if target:
                print(f"   ✅ Setor encontrado: {target['name']} (Meta: {target['max_employees']})")
            else:
                print(f"   ❌ Setor {SECTOR_ID} nao encontrado na lista")
    except Exception as e:
        print(f"   Erro: {e}")

    # 2. Tentar PUT direto
    print(f"\n2. PUT /api/smart-flow/sectors/{SECTOR_ID} (Form Data)")
    data = {"max_employees": 7, "name": "Recebimento"}
    try:
        r = requests.put(f"{BASE_URL}/api/smart-flow/sectors/{SECTOR_ID}", data=data)
        print(f"   Status: {r.status_code}")
        print(f"   Response: {r.text}")
    except Exception as e:
        print(f"   Erro: {e}")

    # 3. Tentar PUT com barra no final
    print(f"\n3. PUT /api/smart-flow/sectors/{SECTOR_ID}/ (Com barra)")
    try:
        r = requests.put(f"{BASE_URL}/api/smart-flow/sectors/{SECTOR_ID}/", data=data)
        print(f"   Status: {r.status_code}")
        print(f"   Response: {r.text}")
    except Exception as e:
        print(f"   Erro: {e}")

    # 4. Tentar POST (as vezes usado como fallback)
    print(f"\n4. POST /api/smart-flow/sectors/{SECTOR_ID}")
    try:
        r = requests.post(f"{BASE_URL}/api/smart-flow/sectors/{SECTOR_ID}", data=data)
        print(f"   Status: {r.status_code}")
        print(f"   Response: {r.text}")
    except Exception as e:
        print(f"   Erro: {e}")

if __name__ == "__main__":
    test_routes()
