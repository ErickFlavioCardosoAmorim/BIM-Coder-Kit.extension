# -*- coding: utf-8 -*-
__title__ = "Luminarias"
__doc__ = """
Lista e exporta elementos IFC cujo nome contem LUMINARIA.
"""
import codecs
import csv
import difflib
import math
import os
import re
import time
import unicodedata

import clr
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BuiltInCategory,
    Element,
    ElementTransformUtils,
    FamilyInstance,
    FamilySymbol,
    FilteredElementCollector,
    ElementId,
    Level,
    Line,
    LocationCurve,
    LocationPoint,
    RevitLinkInstance,
    Structure,
    XYZ
)
from pyrevit import revit, script, forms


# ETAPA 1 - Permite ao usuario selecionar o vinculo IFC no Revit.
forms.alert(
    "Selecione o vinculo IFC no projeto Revit.",
    title="Selecionar vinculo"
)
vinculo_ifc = revit.pick_element()
if not isinstance(vinculo_ifc, RevitLinkInstance):
    forms.alert(
        "O elemento selecionado nao e um vinculo Revit/IFC.",
        title="Selecao invalida"
    )
    script.exit()

documento_ifc = vinculo_ifc.GetLinkDocument()
if not documento_ifc:
    forms.alert(
        "Nao foi possivel acessar o documento do vinculo. "
        "Verifique se ele esta carregado.",
        title="Vinculo indisponivel"
    )
    script.exit()

nome_vinculo = vinculo_ifc.Name
transformacao_vinculo = vinculo_ifc.GetTotalTransform()


# ETAPA 3 - Funcoes auxiliares para ler nomes e parametros dos elementos.
def nome_elemento(elemento):
    try:
        return Element.Name.__get__(elemento) or ""
    except Exception:
        return ""


def valor_parametro(elemento, nome_parametro):
    for parametro in elemento.Parameters:
        if (parametro.Definition and
                parametro.Definition.Name.lower() == nome_parametro.lower()):
            return (parametro.AsString() or parametro.AsValueString() or "")
    return ""


def nome_tipo_elemento(elemento):
    try:
        tipo_id = elemento.GetTypeId()
        if not tipo_id or tipo_id == ElementId.InvalidElementId:
            return ""
        return nome_elemento(elemento.Document.GetElement(tipo_id))
    except Exception:
        return ""


def tipo_ifc_legivel(elemento):
    for nome_parametro in ("IfcType", "IfcObjectType", "ObjectType", "IfcName", "Name"):
        valor = valor_parametro(elemento, nome_parametro)
        if valor:
            valor_normalizado = normalizar(valor)
            if valor_normalizado and "vinculo" not in valor_normalizado and "link" not in valor_normalizado:
                return valor

    nome = nome_elemento(elemento)
    if nome:
        nome_normalizado = normalizar(nome)
        if nome_normalizado and "vinculo" not in nome_normalizado and "link" not in nome_normalizado:
            return nome

    nome_tipo = nome_tipo_elemento(elemento)
    if nome_tipo:
        nome_normalizado = normalizar(nome_tipo)
        if nome_normalizado and "vinculo" not in nome_normalizado and "link" not in nome_normalizado:
            return nome_tipo

    categoria = categoria_elemento(elemento)
    if categoria:
        categoria_normalizada = normalizar(categoria)
        if categoria_normalizada and "vinculo" not in categoria_normalizada and "link" not in categoria_normalizada:
            return categoria

    return "Luminaria IFC"


def definir_parametro(elemento, nomes_parametro, valor):
    for nome_parametro in nomes_parametro:
        parametro = elemento.LookupParameter(nome_parametro)
        if parametro and not parametro.IsReadOnly:
            parametro.Set(valor or "")
            return True
    return False


def categoria_elemento(elemento):
    try:
        return elemento.Category.Name if elemento.Category else ""
    except Exception:
        return ""


def eh_luminaria(nome, nome_tipo, categoria):
    texto = "{} {} {}".format(nome, nome_tipo, categoria).lower()
    return ("luminaria" in normalizar(texto) or
            "lightingfixture" in normalizar(texto) or
            "lightingfixtures" in normalizar(texto))


def documentos_ifc():
    return [(documento_ifc, nome_vinculo)]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(caractere for caractere in texto
                     if not unicodedata.combining(caractere))
    return "".join(
        caractere for caractere in texto.lower()
        if caractere.isalnum()
    )


def camada_luminaria(nome):
    texto = nome or ""
    if not texto:
        return ""

    texto = texto.strip()
    texto = texto.replace("_", " ")
    texto = re.sub(r"\s+", " ", texto)

    padrao = r"\s*[-\/]\s*(?:\d+\s*[xX]\s*\d+\s*(?:W|WATTS|WATT)?|\d+\s*(?:W|L|LM)|\d+\s*[xX]\s*\d+\s*(?:L|LM)|[A-Z0-9]+\s*[-/]\s*\d+)$"
    texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s*[-\/]\s*$", "", texto)
    texto = re.sub(r"\s{2,}", " ", texto).strip()
    return texto or "Luminaria"


def encontrar_simbolo(nome, indice):
    chave_nome = normalizar(nome)
    if chave_nome in indice:
        return indice[chave_nome]

    melhor_simbolo = None
    melhor_nota = 0.0
    for chave, simbolo in indice.items():
        if chave in chave_nome or chave_nome in chave:
            return simbolo
        nota = difflib.SequenceMatcher(None, chave_nome, chave).ratio()
        if nota > melhor_nota:
            melhor_nota = nota
            melhor_simbolo = simbolo
    return melhor_simbolo if melhor_nota >= 0.25 else None


def tipo_elemento(elemento):
    try:
        return elemento.Symbol.FamilyName + ": " + Element.Name.__get__(elemento.Symbol)
    except Exception:
        return elemento.GetType().Name


def nome_simbolo(simbolo):
    familia = getattr(simbolo, "FamilyName", "")
    tipo = nome_elemento(simbolo)
    return "{}: {}".format(familia, tipo).strip(": ")


def chave_exibicao(objeto):
    if objeto["guid_ifc"]:
        return ("guid", normalizar(objeto["guid_ifc"]))
    ponto = objeto["ponto"]
    coordenadas = tuple(round(getattr(ponto, eixo), 3) for eixo in ("X", "Y", "Z")) if ponto else None
    return (
        "dados",
        normalizar(objeto["origem"]),
        normalizar(objeto["nome"]),
        normalizar(objeto["tipo"]),
        coordenadas
    )


def eixo_rotacao_validado(objeto):
    eixo = objeto.get("eixo_rotacao", None)
    if eixo is None or eixo.IsZeroLength():
        eixo = XYZ.BasisZ
    try:
        return eixo.Normalize()
    except Exception:
        return XYZ.BasisZ


def exportar_coordenadas(caminho, objetos):
    caminho_original = caminho
    numero = 1
    while True:
        try:
            arquivo = codecs.open(caminho, "w", "utf-8")
            break
        except IOError as erro:
            if getattr(erro, "errno", None) != 32:
                raise
            pasta = os.path.dirname(caminho_original)
            nome, extensao = os.path.splitext(
                os.path.basename(caminho_original)
            )
            caminho = os.path.join(
                pasta, "{}_{}{}".format(nome, numero, extensao)
            )
            numero += 1
    try:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow((
            "Nome", "Tipo", "IfcGUID", "IfcEntity", "X_ft", "Y_ft",
            "Z_ft", "EixoX", "EixoY", "EixoZ",
            "Rotacao_rad", "Rotacao_graus"
        ))
        for objeto in objetos:
            ponto = objeto["ponto"]
            eixo = objeto.get("eixo_rotacao", XYZ(0, 0, 1))
            escritor.writerow((
                objeto["nome"],
                objeto["tipo"],
                objeto["guid_ifc"],
                objeto["entidade_ifc"],
                ponto.X if ponto else "",
                ponto.Y if ponto else "",
                ponto.Z if ponto else "",
                eixo.X if eixo else "",
                eixo.Y if eixo else "",
                eixo.Z if eixo else "",
                objeto["angulo"] if ponto else "",
                math.degrees(objeto["angulo"]) if ponto else ""
            ))
    finally:
        arquivo.close()
    return caminho


def ler_coordenadas(caminho):
    objetos = []
    with codecs.open(caminho, "r", "utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=";")
        for linha in leitor:
            ponto = None
            usa_pes = "X_ft" in linha
            x = linha.get("X_ft", linha.get("X", ""))
            y = linha.get("Y_ft", linha.get("Y", ""))
            z = linha.get("Z_ft", linha.get("Z", ""))
            if x and y and z:
                fator_unidade = 1.0 if usa_pes else 3.280839895
                ponto = XYZ(
                    float(x.replace(",", ".")) * fator_unidade,
                    float(y.replace(",", ".")) * fator_unidade,
                    float(z.replace(",", ".")) * fator_unidade
                )
            eixo_x = linha.get("EixoX", "0").replace(",", ".")
            eixo_y = linha.get("EixoY", "0").replace(",", ".")
            eixo_z = linha.get("EixoZ", "1").replace(",", ".")
            try:
                eixo_rotacao = XYZ(
                    float(eixo_x),
                    float(eixo_y),
                    float(eixo_z)
                )
            except Exception:
                eixo_rotacao = XYZ(0, 0, 1)
            objetos.append({
                "origem": os.path.basename(caminho),
                "nome": linha.get("Nome", ""),
                "tipo": linha.get("Tipo", ""),
                "guid_ifc": linha.get("IfcGUID", ""),
                "entidade_ifc": linha.get("IfcEntity", ""),
                "ponto": ponto,
                "angulo": float(
                    (linha.get("Rotacao_rad", linha.get("Rotacao", "")) or
                     "0").replace(",", ".")
                ),
                "eixo_rotacao": eixo_rotacao
            })
    return objetos


def centro_geometria_elemento(elemento):
    try:
        caixa = elemento.get_BoundingBox(None)
        if caixa and caixa.Min.DistanceTo(caixa.Max) > 0.000001:
            return (caixa.Min + caixa.Max) * 0.5
    except Exception:
        pass

    try:
        localizacao = elemento.Location
        if isinstance(localizacao, LocationPoint):
            return localizacao.Point
    except Exception:
        pass

    try:
        localizacao = elemento.Location
        if isinstance(localizacao, LocationCurve):
            curva = localizacao.Curve
            return curva.Evaluate(0.5, True)
    except Exception:
        pass

    return None


def vetor_direcao_elemento(elemento):
    try:
        localizacao = elemento.Location
    except Exception:
        localizacao = None

    if isinstance(localizacao, LocationCurve):
        try:
            curva = localizacao.Curve
            ponto_inicio = curva.GetEndPoint(0)
            ponto_fim = curva.GetEndPoint(1)
            vetor = ponto_fim - ponto_inicio
            if vetor.GetLength() > 0.000001:
                return vetor.Normalize()
        except Exception:
            pass

    try:
        caixa = elemento.get_BoundingBox(None)
        if caixa and caixa.Min.DistanceTo(caixa.Max) > 0.000001:
            delta = caixa.Max - caixa.Min
            maior = max(abs(delta.X), abs(delta.Y), abs(delta.Z))
            if abs(delta.X) == maior and abs(delta.X) > 0.000001:
                return XYZ(1.0, 0.0, 0.0)
            if abs(delta.Y) == maior and abs(delta.Y) > 0.000001:
                return XYZ(0.0, 1.0, 0.0)
            if abs(delta.Z) == maior and abs(delta.Z) > 0.000001:
                return XYZ(0.0, 0.0, 1.0)
    except Exception:
        pass

    return XYZ(1.0, 0.0, 0.0)


def localizacao_elemento(elemento):
    """
    Retorna:
        ponto      = posição da luminária no documento IFC
        angulo     = rotação em torno do eixo Z, em radianos
        vetor      = direção horizontal da luminária

    Prioridade:
        1. LocationPoint.Rotation
        2. LocationCurve
        3. BoundingBox (somente como último recurso)

    Observação:
        O ângulo retornado é o ângulo da direção no plano XY.
    """

    eixo_rotacao = XYZ.BasisZ

    # ---------------------------------------------------------
    # 1. LocationPoint: usar diretamente a rotação da instância
    # ---------------------------------------------------------
    try:
        localizacao = elemento.Location

        if isinstance(localizacao, LocationPoint):
            ponto = localizacao.Point

            if ponto:
                angulo = localizacao.Rotation

                vetor = XYZ(
                    math.cos(angulo),
                    math.sin(angulo),
                    0.0
                )

                return ponto, angulo, vetor

    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. LocationCurve: usar a direção da curva
    # ---------------------------------------------------------
    try:
        localizacao = elemento.Location

        if isinstance(localizacao, LocationCurve):
            curva = localizacao.Curve

            ponto_inicio = curva.GetEndPoint(0)
            ponto_fim = curva.GetEndPoint(1)

            vetor = ponto_fim - ponto_inicio

            if vetor.GetLength() > 0.000001:
                vetor = vetor.Normalize()

                # Para luminárias, considera somente a direção no XY.
                vetor_xy = XYZ(vetor.X, vetor.Y, 0.0)

                if vetor_xy.GetLength() > 0.000001:
                    vetor_xy = vetor_xy.Normalize()
                    angulo = math.atan2(vetor_xy.Y, vetor_xy.X)

                    return (
                        curva.Evaluate(0.5, True),
                        angulo,
                        vetor_xy
                    )

    except Exception:
        pass

    # ---------------------------------------------------------
    # 3. BoundingBox: último recurso
    # ---------------------------------------------------------
    try:
        caixa = elemento.get_BoundingBox(None)

        if caixa:
            ponto = (caixa.Min + caixa.Max) * 0.5

            delta = caixa.Max - caixa.Min

            if abs(delta.X) >= abs(delta.Y):
                vetor = XYZ(1.0, 0.0, 0.0)
            else:
                vetor = XYZ(0.0, 1.0, 0.0)

            angulo = math.atan2(vetor.Y, vetor.X)

            return ponto, angulo, vetor

    except Exception:
        pass

    return None, 0.0, XYZ.BasisX


# ETAPA 5 - Coleta os elementos IFC cujo nome contem LUMINARIA.
objetos_luminaria = []
chaves_ifc = set()
for documento, origem in documentos_ifc():
    for objeto in (
        FilteredElementCollector(documento)
        .OfCategory(BuiltInCategory.OST_LightingFixtures)
        .WhereElementIsNotElementType()
        .ToElements()
    ):
        nome = nome_elemento(objeto)
        nome_tipo = tipo_ifc_legivel(objeto)
        categoria = categoria_elemento(objeto)
        ponto, angulo, vetor_direcao = localizacao_elemento(objeto)

        if ponto:
            # -------------------------------------------------
            # IFC -> sistema de coordenadas do projeto Revit
            # -------------------------------------------------
            ponto = transformacao_vinculo.OfPoint(ponto)

            # -------------------------------------------------
            # Transforma também a direção da luminária.
            # Isso é importante quando o vínculo IFC possui
            # transformação/rotação própria.
            # -------------------------------------------------
            if vetor_direcao is None or vetor_direcao.IsZeroLength():
                vetor_direcao = XYZ.BasisX

            vetor_direcao = vetor_direcao.Normalize()

            vetor_direcao_revit = transformacao_vinculo.OfVector(
                vetor_direcao
            )

            if vetor_direcao_revit.IsZeroLength():
                vetor_direcao_revit = XYZ.BasisX

            vetor_direcao_revit = vetor_direcao_revit.Normalize()

            # Considera somente a direção horizontal para a
            # rotação da luminária em torno do eixo Z.
            vetor_xy = XYZ(
                vetor_direcao_revit.X,
                vetor_direcao_revit.Y,
                0.0
            )

            if vetor_xy.GetLength() > 0.000001:
                vetor_xy = vetor_xy.Normalize()

                # Recalcula o ângulo já no sistema do projeto.
                angulo = math.atan2(
                    vetor_xy.Y,
                    vetor_xy.X
                )

            # Eixo de rotação transformado para o projeto.
            eixo_rotacao = transformacao_vinculo.OfVector(
                XYZ.BasisZ
            )

            if eixo_rotacao.IsZeroLength():
                eixo_rotacao = XYZ.BasisZ

            eixo_rotacao = eixo_rotacao.Normalize()
        objeto_luminaria = {
            "origem": origem,
            "nome": nome,
            "tipo": nome_tipo or tipo_elemento(objeto),
            "categoria": categoria,
            "guid_ifc": valor_parametro(objeto, "IfcGUID"),
            "entidade_ifc": valor_parametro(objeto, "IfcEntity"),
            "ponto": ponto,
            "angulo": angulo,
            "eixo_rotacao": eixo_rotacao
        }
        chave = chave_exibicao(objeto_luminaria)
        if chave not in chaves_ifc:
            chaves_ifc.add(chave)
            objetos_luminaria.append(objeto_luminaria)


# ETAPA 6 - Indexa familias e tipos de luminaria carregados no Revit.
def simbolos_de_luminaria():
    simbolos = (
        FilteredElementCollector(revit.doc)
        .OfClass(FamilySymbol)
        .OfCategory(BuiltInCategory.OST_LightingFixtures)
        .ToElements()
    )
    indice = {}
    for simbolo in simbolos:
        try:
            familia = simbolo.Family.Name
        except Exception:
            familia = getattr(simbolo, "FamilyName", "")
        tipo = nome_elemento(simbolo)
        for chave in (familia, tipo, familia + ": " + tipo):
            chave_normalizada = normalizar(chave)
            if chave_normalizada and chave_normalizada not in indice:
                indice[chave_normalizada] = simbolo
    return indice


def selecionar_mapping_ifc_revit(familias_ifc, familias_revit):
    mapeamento = {}
    familias_ifc_unicas = sorted(set(familias_ifc))
    if not familias_ifc_unicas:
        return mapeamento

    familias_revit = sorted(set(familias_revit))
    if not familias_revit:
        return mapeamento

    for indice, nome_ifc in enumerate(familias_ifc_unicas, 1):
        label_ifc = "LUM {}".format(indice)
        opcoes = ["Ignorar esta família"] + familias_revit
        escolha = forms.SelectFromList.show(
            opcoes,
            title="{} = {} | selecione a família Revit compatível".format(
                label_ifc,
                nome_ifc
            ),
            button_name="Confirmar família",
            multiselect=False
        )
        if escolha and escolha != "Ignorar esta família":
            mapeamento[nome_ifc] = escolha

    return mapeamento


# ETAPA 7 - Coleta as luminarias que ja existem no projeto Revit.
def luminarias_existentes():
    return (
        FilteredElementCollector(revit.doc)
        .OfClass(FamilyInstance)
        .ToElements()
    )


# ETAPA 8 - Mostra a quantidade e os dados encontrados no IFC.
output = script.get_output()
output.close_others()
quantidade_ifc = len(objetos_luminaria)
output.print_md("**Luminarias encontradas no IFC:** {}".format(quantidade_ifc))
categorias_ifc = sorted(set(
    objeto["categoria"] for objeto in objetos_luminaria
    if objeto.get("categoria")
))
if categorias_ifc:
    output.print_md("**Categorias IFC encontradas:** {}".format(
        ", ".join(categorias_ifc)
    ))

if not objetos_luminaria:
    forms.alert(
        "Nenhuma luminaria foi encontrada no arquivo IFC.",
        title="Resultado da busca"
    )
    script.exit()

objetos_filtrados = list(objetos_luminaria)
tipos_disponiveis = sorted(set(
    camada_luminaria(objeto["tipo"]) for objeto in objetos_filtrados
))
output.print_md("**Tipos IFC disponiveis:** {}".format(
    ", ".join(tipos_disponiveis)
))
if not tipos_disponiveis:
    forms.alert("Nenhum tipo de luminaria IFC foi encontrado.", title="Cancelado")
    script.exit()

tipos_selecionados = list(tipos_disponiveis)
if not tipos_selecionados:
    forms.alert("Nenhuma família IFC foi localizada.", title="Cancelado")
    script.exit()

familias_revit_disponiveis = sorted({nome_simbolo(simbolo) for simbolo in simbolos_de_luminaria().values()})
if not familias_revit_disponiveis:
    forms.alert(
        "Nenhuma família Revit de luminária foi encontrada no projeto.",
        title="Familias Revit indisponíveis"
    )
    script.exit()

mapeamento_familias_ifc_revit = selecionar_mapping_ifc_revit(
    tipos_selecionados,
    familias_revit_disponiveis
)
if not mapeamento_familias_ifc_revit:
    forms.alert(
        "Nenhuma família Revit foi relacionada para as famílias IFC selecionadas.",
        title="Mapeamento cancelado"
    )
    script.exit()

objetos_luminaria = [
    objeto for objeto in objetos_filtrados
    if camada_luminaria(objeto["tipo"]) in mapeamento_familias_ifc_revit
]
output.print_md("**Tipos IFC selecionados:** {}".format(
    ", ".join(tipos_selecionados)
))
output.print_md("**Mapeamento IFC x Revit:**")
for nome_ifc, nome_revit in sorted(mapeamento_familias_ifc_revit.items()):
    output.print_md("- {} -> {}".format(nome_ifc, nome_revit))
output.print_md("**Luminarias selecionadas:** {}".format(
    len(objetos_luminaria)
))

caminho_csv = forms.save_file(
    title="Salvar coordenadas das luminarias IFC",
    default_name="luminarias_ifc.csv",
    files_filter="Arquivo CSV (*.csv)|*.csv"
)
if not caminho_csv:
    forms.alert("O arquivo CSV e necessario para continuar.", title="Cancelado")
    script.exit()
caminho_csv = exportar_coordenadas(caminho_csv, objetos_luminaria)
objetos_luminaria = ler_coordenadas(caminho_csv)
output.print_md("**Coordenadas salvas e lidas do CSV:** {}".format(caminho_csv))
output.print_md("**Rotações IFC:** 0° / 90° / 180° serão aplicadas conforme os dados lidos.")

# ETAPA 9 - Compara cada luminaria IFC com familias e instancias existentes.
indice_simbolos = simbolos_de_luminaria()
output.print_md("**Tipos de luminaria encontrados no Revit:** {}".format(
    len(indice_simbolos)
))
simbolos_listados = {}
for simbolo in indice_simbolos.values():
    simbolos_listados[str(simbolo.Id)] = nome_simbolo(simbolo)
if simbolos_listados:
    output.print_md("**Familias/tipos disponiveis:**")
    for nome in sorted(simbolos_listados.values()):
        output.print_md("- {}".format(nome))

if not indice_simbolos:
    forms.alert(
        "Nenhuma familia ou tipo de luminaria foi encontrado no Revit.\n\n"
        "Carregue uma familia na categoria Luminarias e execute novamente.",
        title="Nada encontrado no Revit"
    )
    script.exit()

para_inserir = []
sem_familia = []
sem_posicao = []
ja_existentes = []
erros_insercao = []

for objeto in objetos_luminaria:
    simbolo = None
    chave_objeto = camada_luminaria(objeto["tipo"] or objeto["nome"] or "")
    nome_revit_map = mapeamento_familias_ifc_revit.get(chave_objeto)
    if nome_revit_map:
        for simbolo_item in indice_simbolos.values():
            if nome_simbolo(simbolo_item) == nome_revit_map:
                simbolo = simbolo_item
                break
    if not simbolo:
        simbolo = encontrar_simbolo(objeto["tipo"], indice_simbolos)
    if not simbolo:
        sem_familia.append(objeto["nome"])
        objeto["status"] = "NAO ALOCADA - familia nao encontrada"
    elif not objeto["ponto"]:
        sem_posicao.append(objeto["nome"])
        objeto["status"] = "NAO ALOCADA - coordenada nao encontrada"
    else:
        # Mesmo que o objeto ja exista no projeto, a luminaria deve continuar sendo
        # inserida no ponto IFC solicitado. A checagem de duplicidade fica apenas
        # como informacao de diagnostico e nao bloqueia a criacao.
        ja_existentes.append(objeto["nome"])
        para_inserir.append((objeto, simbolo))


def nivel_da_luminaria(ponto, niveis):
    niveis_abaixo = [nivel for nivel in niveis
                     if nivel.Elevation <= ponto.Z]
    if niveis_abaixo:
        return max(niveis_abaixo, key=lambda nivel: nivel.Elevation)
    return min(niveis, key=lambda nivel: abs(nivel.Elevation - ponto.Z))


def inserir_luminaria(objeto, simbolo, niveis):
    tipo_alocacao = str(simbolo.Family.FamilyPlacementType)
    tipo_alocacao_lower = tipo_alocacao.lower()

    if "hosted" in tipo_alocacao_lower:
        raise Exception(
            "familia '{}' e hospedada ({}); carregue uma familia nao "
            "hospedada ou crie o teto/face hospedeiro antes da alocacao".format(
                simbolo.FamilyName,
                tipo_alocacao
            )
        )

    ponto = XYZ(
        objeto["ponto"].X,
        objeto["ponto"].Y,
        objeto["ponto"].Z
    )

    try:
        return revit.doc.Create.NewFamilyInstance(
            ponto,
            simbolo,
            Structure.StructuralType.NonStructural
        )
    except Exception:
        if ("onelevelbased" in tipo_alocacao_lower or
                "workplanebased" in tipo_alocacao_lower):
            if not niveis:
                raise Exception(
                    "nenhum nivel encontrado para a familia {}".format(
                        simbolo.FamilyName
                    )
                )
            nivel = nivel_da_luminaria(ponto, niveis)
            return revit.doc.Create.NewFamilyInstance(
                ponto,
                simbolo,
                nivel,
                Structure.StructuralType.NonStructural
            )
        raise


def rotacionar_instancia(instancia, objeto):
    """
    Aplica à instância Revit a rotação calculada a partir da
    orientação da luminária no IFC.

    O ângulo é armazenado em radianos.
    Não adiciona mais um deslocamento fixo de 90 graus.
    """

    angulo = objeto.get("angulo", 0.0)

    ponto = objeto.get("ponto")

    if ponto is None:
        return

    if abs(angulo) <= 0.000001:
        return

    eixo_rotacao = eixo_rotacao_validado(objeto)

    eixo = Line.CreateBound(
        ponto,
        ponto + eixo_rotacao
    )

    # ---------------------------------------------------------
    # Tenta primeiro LocationPoint.Rotate()
    # ---------------------------------------------------------
    try:
        localizacao = instancia.Location

        if isinstance(localizacao, LocationPoint):
            try:
                localizacao.Rotate(
                    eixo,
                    angulo
                )
                return
            except Exception:
                pass

    except Exception:
        pass

    # ---------------------------------------------------------
    # Fallback: ElementTransformUtils.RotateElement()
    # ---------------------------------------------------------
    try:
        ElementTransformUtils.RotateElement(
            revit.doc,
            instancia.Id,
            eixo,
            angulo
        )

    except Exception as erro:
        raise Exception(
            "Erro ao rotacionar luminaria '{}': {}".format(
                objeto.get("nome", ""),
                erro
            )
        )


# ETAPA 10 - Insere no Revit somente as luminarias compativeis e novas.
criadas = 0
niveis = list(
    FilteredElementCollector(revit.doc)
    .OfClass(Level)
    .ToElements()
)
total_para_inserir = len(para_inserir)
intervalo_insercao = 0.05
output.print_md("**Intervalo entre insercoes:** {} segundo(s)".format(
    intervalo_insercao
))
if para_inserir:
    for indice, (objeto, simbolo) in enumerate(para_inserir, 1):
        try:
            output.print_md(
                "- Inserindo {}/{}: {}".format(
                    indice, total_para_inserir, objeto["nome"]
                )
            )
            with revit.Transaction(
                    "Inserir luminaria {}/{}".format(
                        indice, total_para_inserir
                    )):
                if not simbolo.IsActive:
                    simbolo.Activate()
                    revit.doc.Regenerate()
                instancia = inserir_luminaria(objeto, simbolo, niveis)
                rotacionar_instancia(instancia, objeto)
                parametro_guid = instancia.LookupParameter("IfcGUID")
                if (objeto["guid_ifc"] and parametro_guid and
                        not parametro_guid.IsReadOnly):
                    parametro_guid.Set(objeto["guid_ifc"])
                definir_parametro(
                    instancia,
                    ("IfcName", "Nome IFC", "Comments"),
                    objeto["nome"]
                )
                definir_parametro(
                    instancia,
                    ("IfcSource", "Origem IFC"),
                    objeto["origem"]
                )
                revit.doc.Regenerate()
            criadas += 1
            objeto["status"] = "ALOCADA"
            if intervalo_insercao > 0.0 and indice < total_para_inserir:
                time.sleep(intervalo_insercao)
        except Exception as erro:
            objeto["status"] = "NAO ALOCADA - {}".format(erro)
            erros_insercao.append(
                "{}: {}".format(objeto["nome"], erro)
            )

# ETAPA 11 - Exibe o resultado individual da alocacao.
for objeto in objetos_luminaria:
    output.print_md(
        "- **{}** | {} | {} | Coordenada: {} | Familia Revit: {} | "
        "Status: **{}**".format(
            objeto["nome"],
            objeto["tipo"],
            objeto["origem"],
            "({}, {}, {})".format(
                round(objeto["ponto"].X, 3),
                round(objeto["ponto"].Y, 3),
                round(objeto["ponto"].Z, 3)
            ) if objeto["ponto"] else "nao encontrada",
            nome_simbolo(next(
                (simbolo for item, simbolo in para_inserir
                 if item is objeto),
                None
            )) if any(item is objeto for item, simbolo in para_inserir)
            else "nao encontrada",
            objeto.get("status", "NAO ALOCADA")
        )
    )

# ETAPA 12 - Exibe o resumo da comparacao e da insercao.
output.print_md("**Luminarias posicionadas:** {}".format(criadas))
if sem_familia:
    output.print_md("**Sem familia compativel:** {}".format(
        ", ".join(sem_familia)
    ))
if sem_posicao:
    output.print_md(
        "**COORDENADAS NAO ENCONTRADAS (nao alocadas):** {}".format(
            ", ".join(sem_posicao)
        )
    )
if erros_insercao:
    output.print_md("**Falhas de insercao:**")
    for erro in erros_insercao:
        output.print_md("- {}".format(erro))

forms.alert(
    "CSV utilizado:\n{}\n\nForam alocadas {} luminaria(s).\n"
    "Coordenadas nao encontradas: {} luminaria(s).".format(
        caminho_csv, criadas, len(sem_posicao)
    ),
    "IFC"
)
