import requests
import json

# URL do servidor
BASE_URL = "http://127.0.0.1:8000"

def test_update_sector_sync():
    print("="*60)
    print("TESTE DE SINCRONIZAÇÃO DE SETOR")
    print("="*60)
    
    # 1. Login (simulado ou necessário se houver auth)
    # Assumindo que o endpoint precisa de cookie de sessão, mas localhost pode estar aberto
    # Vamos tentar direto primeiro
    
    # 2. Dados para atualização: Setor 1 (Recebimento) -> Meta 8
    sector_id = 1
    new_target = 8
    
    payload = {
        "name": "Recebimento",
        "max_employees": new_target,
        "color": "blue"
    }
    
    print(f"📡 Enviando PUT para /api/smart-flow/sectors/{sector_id}")
    print(f"   Payload: {payload}")
    
    try:
        # Usando FormData como o frontend faz
        response = requests.put(
            f"{BASE_URL}/api/smart-flow/sectors/{sector_id}",
            data=payload
        )
        
        print(f"\n📥 Status Code: {response.status_code}")
        print(f"📥 Response: {response.text}")
        
        if response.status_code == 200:
            print("\n✅ Sucesso na chamada API!")
            print("Agora verifique os logs do servidor para:")
            print("1. '🔧 UPDATE_SECTOR CHAMADO'")
            print(f"2. '🔄 Meta alterada para setor Recebimento: {new_target}'")
            print("3. '💾 SectorConfiguration atualizado'")
        else:
            print(f"\n❌ Erro na chamada: {response.status_code}")
            
    except Exception as e:
        print(f"\n❌ Exceção: {e}")

if __name__ == "__main__":
    test_update_sector_sync()
