// Função para formatar números no padrão brasileiro
function formatBR(value) {
    // Remove tudo exceto números, vírgula e ponto
    let str = String(value).trim();
    
    // Remove pontos (separador de milhares)
    str = str.replace(/\./g, '');
    
    // Converte vírgula para ponto para parseFloat
    str = str.replace(',', '.');
    
    // Parse para número
    const number = parseFloat(str);
    
    if (isNaN(number)) return '0,00';
    
    // Formata com separador de milhares e decimal brasileiro
    return number.toLocaleString('pt-BR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// Função para parsear número brasileiro para float
function parseBR(value) {
    let str = String(value).trim();
    str = str.replace(/\./g, '').replace(',', '.');
    return parseFloat(str) || 0;
}
