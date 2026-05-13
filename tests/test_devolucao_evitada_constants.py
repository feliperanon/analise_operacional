from devolucao_evitada_constants import EVITADA_TIPO_LABELS, EVITADA_TIPOS_ORDENADOS, label_tipo_evitada


def test_tipos_ordenados_cobre_labels():
    assert set(EVITADA_TIPOS_ORDENADOS) == set(EVITADA_TIPO_LABELS.keys())


def test_label_tipo_desconhecido_retorna_proprio():
    assert label_tipo_evitada("xyz_desconhecido") == "xyz_desconhecido"
