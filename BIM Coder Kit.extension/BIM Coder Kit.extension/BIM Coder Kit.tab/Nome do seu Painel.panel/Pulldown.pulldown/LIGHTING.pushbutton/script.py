# -*- coding: utf-8 -*-
__title__ = "Luminarias \nIFC"
__doc__ = """
VERSÃO: RV 13.0.0 05/09/2026
Lê luminárias do IFC diretamente em memória e insere no Revit.
"""
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
    GeometryInstance,
    Options,
    Level,
    Line,
    LocationCurve,
    LocationPoint,
    RevitLinkInstance,
    Structure,
    XYZ
)
from pyrevit import revit, script, forms

from System.Windows import (Window, Thickness, HorizontalAlignment, VerticalAlignment, WindowStartupLocation, ResizeMode, FontWeights, TextWrapping, CornerRadius)
from System.Windows.Controls import (
    Grid, RowDefinition, ColumnDefinition, StackPanel,
    TextBlock, TextBox, ComboBox, Button, ScrollViewer, Orientation, ScrollBarVisibility,
    ProgressBar, ListBox, Border
)
from System.Windows import GridLength, GridUnitType, Visibility
from System.Windows.Media import Brushes


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



def pontos_geometria(elemento):
    """
    Lê os pontos da geometria do elemento usando SOMENTE a Revit API.

    A função entra nas GeometryInstance e coleta vértices das
    arestas/meshes. Isso permite descobrir a direção física da
    luminária, em vez de depender somente de LocationPoint.Rotation.
    """
    pontos = []

    try:
        opcoes = Options()
        opcoes.ComputeReferences = False
        geometria = elemento.get_Geometry(opcoes)
    except Exception:
        return pontos

    def coletar(geometria_atual):
        try:
            for geometria_obj in geometria_atual:

                # GeometryInstance: pega a geometria já transformada
                # para a posição da instância.
                if isinstance(geometria_obj, GeometryInstance):
                    try:
                        coletar(geometria_obj.GetInstanceGeometry())
                    except Exception:
                        try:
                            coletar(geometria_obj.GetSymbolGeometry())
                        except Exception:
                            pass
                    continue

                # Solid: coleta pontos das arestas.
                try:
                    arestas = geometria_obj.Edges
                    for aresta in arestas:
                        try:
                            curva = aresta.AsCurve()
                            for ponto in curva.Tessellate():
                                pontos.append(ponto)
                        except Exception:
                            pass
                    continue
                except Exception:
                    pass

                # Mesh: coleta os vértices.
                try:
                    vertices = geometria_obj.Vertices
                    for vertice in vertices:
                        pontos.append(vertice)
                    continue
                except Exception:
                    pass

                # PolyLine, quando existir.
                try:
                    coordenadas = geometria_obj.GetCoordinates()
                    for ponto in coordenadas:
                        pontos.append(ponto)
                except Exception:
                    pass

        except Exception:
            pass

    try:
        coletar(geometria)
    except Exception:
        pass

    return pontos


def eixo_principal_xy(pontos):
    """
    Calcula o eixo principal horizontal da geometria usando PCA 2D.

    Para uma luminária comprida:
        eixo principal = direção do comprimento.

    Para uma luminária quadrada/circular:
        não força uma direção artificial.
    """
    pontos_xy = [
        ponto for ponto in pontos
        if ponto is not None
    ]

    if len(pontos_xy) < 3:
        return None

    media_x = sum(ponto.X for ponto in pontos_xy) / float(len(pontos_xy))
    media_y = sum(ponto.Y for ponto in pontos_xy) / float(len(pontos_xy))

    sxx = 0.0
    syy = 0.0
    sxy = 0.0

    for ponto in pontos_xy:
        dx = ponto.X - media_x
        dy = ponto.Y - media_y
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy

    if (sxx + syy) <= 0.000001:
        return None

    delta = math.sqrt(
        ((sxx - syy) * 0.5) ** 2 +
        sxy * sxy
    )

    maior = ((sxx + syy) * 0.5) + delta
    menor = ((sxx + syy) * 0.5) - delta

    # Se os dois eixos têm praticamente o mesmo tamanho,
    # a geometria não possui uma direção confiável.
    if menor > 0.000001 and maior / menor < 1.05:
        return None

    theta = 0.5 * math.atan2(
        2.0 * sxy,
        sxx - syy
    )

    vetor = XYZ(
        math.cos(theta),
        math.sin(theta),
        0.0
    )

    try:
        return vetor.Normalize()
    except Exception:
        return None


def centro_geometria_pontos(pontos):
    """
    Retorna o centro da caixa envolvente da geometria real.
    """
    if not pontos:
        return None

    min_x = min(ponto.X for ponto in pontos)
    min_y = min(ponto.Y for ponto in pontos)
    min_z = min(ponto.Z for ponto in pontos)

    max_x = max(ponto.X for ponto in pontos)
    max_y = max(ponto.Y for ponto in pontos)
    max_z = max(ponto.Z for ponto in pontos)

    return XYZ(
        (min_x + max_x) * 0.5,
        (min_y + max_y) * 0.5,
        (min_z + max_z) * 0.5
    )


def localizacao_elemento(elemento):
    """
    Retorna:
        ponto      = centro/posição da luminária no IFC
        angulo     = direção física horizontal em radianos
        vetor      = eixo físico horizontal da luminária

    A direção é determinada primeiro pela GEOMETRIA física.
    LocationPoint.Rotation é usada somente para definir o sentido
    (+/-) do eixo quando a geometria permite descobrir um eixo.

    Isso evita depender de uma orientação que pode estar invertida
    em determinados objetos IFC.
    """

    ponto = None
    angulo = 0.0
    vetor = None

    # ---------------------------------------------------------
    # 1. Centro/ponto de inserção IFC.
    # ---------------------------------------------------------
    try:
        localizacao = elemento.Location

        if isinstance(localizacao, LocationPoint):
            ponto = localizacao.Point

        elif isinstance(localizacao, LocationCurve):
            ponto_inicio = localizacao.Curve.GetEndPoint(0)
            ponto_fim = localizacao.Curve.GetEndPoint(1)
            ponto = (ponto_inicio + ponto_fim) * 0.5

    except Exception:
        pass

    # ---------------------------------------------------------
    # 2. Geometria física.
    # ---------------------------------------------------------
    pontos = pontos_geometria(elemento)

    if ponto is None:
        ponto = centro_geometria_pontos(pontos)

    vetor_geometria = eixo_principal_xy(pontos)

    # ---------------------------------------------------------
    # 3. Define o sentido do eixo.
    #
    # O PCA sabe o eixo, mas não sabe se é:
    #     -----> ou <-----
    #
    # LocationPoint.Rotation fornece o sentido de referência
    # do objeto IFC.
    # ---------------------------------------------------------
    if vetor_geometria is not None:
        vetor = vetor_geometria

        try:
            localizacao = elemento.Location
            referencia = None

            if isinstance(localizacao, LocationPoint):
                rotacao = localizacao.Rotation
                referencia = XYZ(
                    math.cos(rotacao),
                    math.sin(rotacao),
                    0.0
                )

            elif isinstance(localizacao, LocationCurve):
                inicio = localizacao.Curve.GetEndPoint(0)
                fim = localizacao.Curve.GetEndPoint(1)
                referencia = fim - inicio
                referencia = XYZ(
                    referencia.X,
                    referencia.Y,
                    0.0
                )

            if referencia and referencia.GetLength() > 0.000001:
                referencia = referencia.Normalize()

                if vetor.DotProduct(referencia) < 0.0:
                    vetor = XYZ(
                        -vetor.X,
                        -vetor.Y,
                        -vetor.Z
                    )

        except Exception:
            pass

    # ---------------------------------------------------------
    # 4. Fallback para objetos sem geometria suficiente.
    # ---------------------------------------------------------
    if vetor is None:
        try:
            localizacao = elemento.Location

            if isinstance(localizacao, LocationPoint):
                rotacao = localizacao.Rotation
                vetor = XYZ(
                    math.cos(rotacao),
                    math.sin(rotacao),
                    0.0
                )

            elif isinstance(localizacao, LocationCurve):
                inicio = localizacao.Curve.GetEndPoint(0)
                fim = localizacao.Curve.GetEndPoint(1)
                delta = fim - inicio
                vetor = XYZ(delta.X, delta.Y, 0.0)

                if vetor.GetLength() > 0.000001:
                    vetor = vetor.Normalize()

        except Exception:
            pass

    if vetor is None:
        vetor = XYZ.BasisX

    try:
        vetor = vetor.Normalize()
    except Exception:
        vetor = XYZ.BasisX

    angulo = math.atan2(vetor.Y, vetor.X)

    return ponto, angulo, vetor


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
            # Transforma a direção física da luminária.
            # OfVector NÃO altera a posição, apenas a direção.
            # -------------------------------------------------
            vetor_direcao = transformacao_vinculo.OfVector(
                vetor_direcao
            )

            if vetor_direcao.IsZeroLength():
                vetor_direcao = XYZ.BasisX

            vetor_direcao = vetor_direcao.Normalize()

            # Só queremos rotação no plano horizontal.
            vetor_xy = XYZ(
                vetor_direcao.X,
                vetor_direcao.Y,
                0.0
            )

            if vetor_xy.GetLength() > 0.000001:
                vetor_xy = vetor_xy.Normalize()
                angulo = math.atan2(
                    vetor_xy.Y,
                    vetor_xy.X
                )

            # O eixo de rotação também acompanha o vínculo IFC.
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
            "vetor_direcao": vetor_direcao,
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
    """
    Tela principal para comparar IFC x Revit.

    Melhorias visuais:
    - seleção de família Revit em cartões grandes;
    - pesquisa rápida das famílias disponíveis;
    - contador de associações;
    - destaque visual para "não selecionado" e "ignorar";
    - nome IFC sempre visível ao lado da escolha Revit;
    - botão de confirmação mais evidente.

    A lógica de mapeamento permanece a mesma:
    IFC -> Família/Tipo Revit ou Ignorar.
    """

    mapeamento = {}

    familias_ifc_unicas = sorted(set(
        item for item in familias_ifc
        if item and item.strip()
    ))
    familias_revit = sorted(set(
        item for item in familias_revit
        if item and item.strip()
    ))

    if not familias_ifc_unicas or not familias_revit:
        return mapeamento

    IGNORAR = "Ignorar esta família"
    opcoes = [IGNORAR] + familias_revit

    janela = Window()
    janela.Title = "Luminárias IFC  |  Associação de famílias Revit"
    janela.Width = 1180
    janela.Height = 820
    janela.MinWidth = 900
    janela.MinHeight = 620
    janela.WindowStartupLocation = WindowStartupLocation.CenterScreen
    janela.ResizeMode = ResizeMode.CanResize
    janela.Background = Brushes.White

    principal = Grid()
    principal.Margin = Thickness(24)

    # 6 linhas:
    # cabeçalho / resumo / pesquisa / títulos / lista / rodapé
    for altura in [62, 42, 58, 38, 1, 68]:
        row = RowDefinition()
        row.Height = GridLength(
            altura,
            GridUnitType.Star if altura == 1 else GridUnitType.Pixel
        )
        principal.RowDefinitions.Add(row)

    # =========================================================
    # CABEÇALHO
    # =========================================================
    cabecalho = Grid()
    cabecalho.ColumnDefinitions.Add(ColumnDefinition())
    cabecalho.ColumnDefinitions.Add(ColumnDefinition())

    titulo_bloco = StackPanel()
    titulo = TextBlock()
    titulo.Text = "SELECIONAR LUMINARIAS"
    titulo.FontSize = 25
    titulo.FontWeight = FontWeights.Bold
    titulo.Foreground = Brushes.Black

    subtitulo = TextBlock()
    subtitulo.Text = (
        "Compare o tipo de luminaria encontrado no IFC e escolha a família no Revit."
    )
    subtitulo.FontSize = 13
    subtitulo.Foreground = Brushes.Gray
    subtitulo.Margin = Thickness(0, 6, 0, 0)

    titulo_bloco.Children.Add(titulo)
    titulo_bloco.Children.Add(subtitulo)

    status = Border()
    status.Background = Brushes.AliceBlue
    status.BorderBrush = Brushes.LightSteelBlue
    status.BorderThickness = Thickness(1)
    status.CornerRadius = CornerRadius(10)
    status.Padding = Thickness(14, 7, 14, 7)
    status.HorizontalAlignment = HorizontalAlignment.Right
    status.VerticalAlignment = VerticalAlignment.Center

    status_text = TextBlock()
    status_text.Text = "0 / {} associados".format(len(familias_ifc_unicas))
    status_text.FontSize = 13
    status_text.FontWeight = FontWeights.Bold
    status_text.Foreground = Brushes.DodgerBlue
    status_text.VerticalAlignment = VerticalAlignment.Center

    status.Child = status_text

    Grid.SetColumn(titulo_bloco, 0)
    Grid.SetColumn(status, 1)
    cabecalho.Children.Add(titulo_bloco)
    cabecalho.Children.Add(status)

    Grid.SetRow(cabecalho, 0)
    principal.Children.Add(cabecalho)

    # =========================================================
    # RESUMO
    # =========================================================
    resumo = Border()
    resumo.Background = Brushes.WhiteSmoke
    resumo.BorderBrush = Brushes.LightGray
    resumo.BorderThickness = Thickness(1)
    resumo.CornerRadius = CornerRadius(9)
    resumo.Padding = Thickness(12, 5, 12, 5)

    resumo_grid = Grid()
    for _ in range(3):
        resumo_grid.ColumnDefinitions.Add(ColumnDefinition())

    def criar_resumo(valor, legenda):
        bloco = StackPanel()
        valor_tb = TextBlock()
        valor_tb.Text = valor
        valor_tb.FontSize = 12
        valor_tb.FontWeight = FontWeights.Bold
        valor_tb.Foreground = Brushes.Black

        legenda_tb = TextBlock()
        legenda_tb.Text = legenda
        legenda_tb.FontSize = 9
        legenda_tb.Foreground = Brushes.Gray

        bloco.Children.Add(valor_tb)
        bloco.Children.Add(legenda_tb)
        return bloco

    r1 = criar_resumo(str(len(familias_ifc_unicas)), "FAMÍLIAS IFC")
    r2 = criar_resumo(str(len(familias_revit)), "FAMÍLIAS REVIT")
    r3 = criar_resumo("→", "ESCOLHA A CORRESPONDÊNCIA")

    Grid.SetColumn(r1, 0)
    Grid.SetColumn(r2, 1)
    Grid.SetColumn(r3, 2)
    resumo_grid.Children.Add(r1)
    resumo_grid.Children.Add(r2)
    resumo_grid.Children.Add(r3)
    resumo.Child = resumo_grid

    Grid.SetRow(resumo, 1)
    principal.Children.Add(resumo)

    # =========================================================
    # TÍTULOS DAS COLUNAS
    # =========================================================
    titulos = Grid()
    titulos.ColumnDefinitions.Add(ColumnDefinition())
    arrow_col = ColumnDefinition()
    arrow_col.Width = GridLength(48)
    titulos.ColumnDefinitions.Add(arrow_col)
    titulos.ColumnDefinitions.Add(ColumnDefinition())

    h_ifc = TextBlock()
    h_ifc.Text = "IFC  •  FAMÍLIA ENCONTRADA"
    h_ifc.FontSize = 10
    h_ifc.FontWeight = FontWeights.Bold
    h_ifc.Foreground = Brushes.DimGray
    h_ifc.Margin = Thickness(6, 0, 0, 0)
    h_ifc.VerticalAlignment = VerticalAlignment.Center

    
    h_revit = TextBlock()
    h_revit.Text = "REVIT  •  ESCOLHA A FAMÍLIA"
    h_revit.FontSize = 10
    h_revit.FontWeight = FontWeights.Bold
    h_revit.Foreground = Brushes.DimGray
    h_revit.VerticalAlignment = VerticalAlignment.Center

    Grid.SetColumn(h_ifc, 0)
    Grid.SetColumn(h_revit, 2)
    titulos.Children.Add(h_ifc)
    titulos.Children.Add(h_revit)

    Grid.SetRow(titulos, 3)
    principal.Children.Add(titulos)

    # =========================================================
    # LISTA
    # =========================================================
    scroll = ScrollViewer()
    scroll.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled

    tabela = Grid()
    tabela.Margin = Thickness(0, 4, 8, 6)
    tabela.ColumnDefinitions.Add(ColumnDefinition())

    seta_col = ColumnDefinition()
    seta_col.Width = GridLength(48)
    tabela.ColumnDefinitions.Add(seta_col)

    tabela.ColumnDefinitions.Add(ColumnDefinition())
    combos = []
    dados_linhas = []

    for i, nome_ifc in enumerate(familias_ifc_unicas):
        row = RowDefinition()
        row.Height = GridLength(92)
        tabela.RowDefinitions.Add(row)

        # -----------------------------------------------------
        # CARTÃO IFC
        # -----------------------------------------------------
        card_ifc = Border()
        card_ifc.Margin = Thickness(0, 5, 8, 5)
        card_ifc.Padding = Thickness(14, 2, 14, 2)
        card_ifc.CornerRadius = CornerRadius(10)
        card_ifc.BorderThickness = Thickness(1)
        card_ifc.BorderBrush = Brushes.LightGray
        card_ifc.Background = Brushes.WhiteSmoke

        bloco_ifc = Grid()
        bloco_ifc.ColumnDefinitions.Add(ColumnDefinition())
        bloco_ifc.ColumnDefinitions.Add(ColumnDefinition())

        info_ifc = StackPanel()
        numero = TextBlock()
        numero.Text = "LUMINÁRIA {:02d}".format(i + 1)
        numero.FontSize = 10
        numero.FontWeight = FontWeights.Bold
        numero.Foreground = Brushes.Gray

        nome = TextBlock()
        nome.Text = nome_ifc
        nome.FontSize = 13
        nome.FontWeight = FontWeights.Bold
        nome.Foreground = Brushes.Black
        nome.TextWrapping = TextWrapping.Wrap
        nome.Margin = Thickness(0, 1, 0, 0)

        info_ifc.Children.Add(numero)
        info_ifc.Children.Add(nome)

        tipo_tag = Border()
        tipo_tag.Background = Brushes.White
        tipo_tag.BorderBrush = Brushes.LightGray
        tipo_tag.BorderThickness = Thickness(1)
        tipo_tag.CornerRadius = CornerRadius(6)
        tipo_tag.Padding = Thickness(7, 1, 7, 3)
        tipo_tag.HorizontalAlignment = HorizontalAlignment.Right
        tipo_tag.VerticalAlignment = VerticalAlignment.Center

        tag_text = TextBlock()
        tag_text.Text = "IFC"
        tag_text.FontSize = 8
        tag_text.FontWeight = FontWeights.Bold
        tag_text.Foreground = Brushes.Gray
        tipo_tag.Child = tag_text

        Grid.SetColumn(info_ifc, 0)
        Grid.SetColumn(tipo_tag, 1)
        bloco_ifc.Children.Add(info_ifc)
        bloco_ifc.Children.Add(tipo_tag)

        card_ifc.Child = bloco_ifc

        # -----------------------------------------------------
        # SETA CENTRAL
        # -----------------------------------------------------
        seta = TextBlock()
        seta.Text = "→"
        seta.FontSize = 10
        seta.FontWeight = FontWeights.Bold
        seta.Foreground = Brushes.Gray
        seta.HorizontalAlignment = HorizontalAlignment.Center
        seta.VerticalAlignment = VerticalAlignment.Center

        # -----------------------------------------------------
        # CARTÃO REVIT
        # -----------------------------------------------------
        card_revit = Border()
        card_revit.Margin = Thickness(8, 0, 0, 5)
        card_revit.Padding = Thickness(12, 4, 12, 8)
        card_revit.CornerRadius = CornerRadius(10)
        card_revit.BorderThickness = Thickness(4)
        card_revit.BorderBrush = Brushes.LightGray
        card_revit.Background = Brushes.White

        bloco_revit = Grid()
        bloco_revit.RowDefinitions.Add(RowDefinition())
        bloco_revit.RowDefinitions.Add(RowDefinition())

        legenda_revit = TextBlock()
        legenda_revit.Text = "FAMÍLIA REVIT"
        legenda_revit.FontSize = 9
        legenda_revit.FontWeight = FontWeights.Bold
        legenda_revit.Foreground = Brushes.Gray
        legenda_revit.Margin = Thickness(2, 0, 0, 3)

        combo = ComboBox()
        for opcao in opcoes:
            combo.Items.Add(opcao)

        combo.SelectedIndex = 0
        combo.FontSize = 12
        combo.MinHeight = 50
        combo.Padding = Thickness(8, 5, 8, 5)
        combo.VerticalContentAlignment = VerticalAlignment.Center
        combo.HorizontalContentAlignment = HorizontalAlignment.Left
        combo.ToolTip = "Selecione a família Revit para este tipo IFC."

        Grid.SetRow(legenda_revit, 0)
        Grid.SetRow(combo, 1)
        bloco_revit.Children.Add(legenda_revit)
        bloco_revit.Children.Add(combo)

        card_revit.Child = bloco_revit

        Grid.SetRow(card_ifc, i)
        Grid.SetColumn(card_ifc, 0)

        Grid.SetRow(seta, i)
        Grid.SetColumn(seta, 1)

        Grid.SetRow(card_revit, i)
        Grid.SetColumn(card_revit, 2)

        tabela.Children.Add(card_ifc)
        tabela.Children.Add(seta)
        tabela.Children.Add(card_revit)

        combos.append((nome_ifc, combo, card_revit))
        dados_linhas.append({
            "nome_ifc": nome_ifc,
            "combo": combo,
            "card": card_revit
        })

    scroll.Content = tabela
    Grid.SetRow(scroll, 4)
    principal.Children.Add(scroll)

    # =========================================================
    # EVENTOS
    # =========================================================
    def atualizar_status():
        associados = 0

        for nome_ifc, combo, card in combos:
            escolha = combo.SelectedItem
            if escolha and str(escolha) != IGNORAR:
                associados += 1
                card.BorderBrush = Brushes.SteelBlue
                card.Background = Brushes.White
            elif escolha and str(escolha) == IGNORAR:
                card.BorderBrush = Brushes.LightGray
                card.Background = Brushes.WhiteSmoke
            else:
                card.BorderBrush = Brushes.LightGray
                card.Background = Brushes.White

        status_text.Text = "{} / {} associados".format(
            associados, len(familias_ifc_unicas)
        )


    # =========================================================
    # RODAPÉ
    # =========================================================
    rodape = Grid()
    rodape.ColumnDefinitions.Add(ColumnDefinition())
    rodape.ColumnDefinitions.Add(ColumnDefinition())


    botoes = StackPanel()
    botoes.Orientation = Orientation.Horizontal
    botoes.HorizontalAlignment = HorizontalAlignment.Right
    botoes.VerticalAlignment = VerticalAlignment.Center

    cancelar = Button()
    cancelar.Content = "CANCELAR"
    cancelar.Width = 110
    cancelar.Height = 40
    cancelar.Margin = Thickness(8, 0, 0, 0)
    cancelar.FontSize = 12

    confirmar = Button()
    confirmar.Content = "CONFIRMAR"
    confirmar.Width = 235
    confirmar.Height = 40
    confirmar.Margin = Thickness(8, 0, 0, 0)
    confirmar.FontSize = 12
    confirmar.FontWeight = FontWeights.Bold
    confirmar.IsDefault = True

    def cancelar_click(sender, args):
        janela.DialogResult = False
        janela.Close()

    def confirmar_click(sender, args):
        resultado = {}

        for nome_ifc, combo, _ in combos:
            escolha = combo.SelectedItem
            if escolha and str(escolha) != IGNORAR:
                resultado[nome_ifc] = str(escolha)

        if not resultado:
            resposta = forms.alert(
                "Nenhum tipo IFC foi associado a uma família Revit.\n\n"
                "Deseja cancelar?",
                title="Comparação vazia",
                options=["Sim", "Não"]
            )
            if resposta != "Sim":
                return

        mapeamento.update(resultado)
        janela.DialogResult = True
        janela.Close()

    cancelar.Click += cancelar_click
    confirmar.Click += confirmar_click

    botoes.Children.Add(cancelar)
    botoes.Children.Add(confirmar)

    Grid.SetColumn(botoes, 1)
    rodape.Children.Add(botoes)

    Grid.SetRow(rodape, 5)
    principal.Children.Add(rodape)

    janela.Content = principal

    atualizar_status()

    if janela.ShowDialog() != True:
        return {}

    return mapeamento

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
        "Nenhuma luminaria foi encontrada no arquivo IFC\nSelceione um arquivo ifc que contenha luminarias.",
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
output.print_md("**Mapeamento IFC x Revit (definido em uma única tela):**")
for nome_ifc, nome_revit in sorted(mapeamento_familias_ifc_revit.items()):
    output.print_md("- {} -> {}".format(nome_ifc, nome_revit))
output.print_md("**Luminarias selecionadas:** {}".format(
    len(objetos_luminaria)
))

# As coordenadas, a direção e a rotação permanecem em memória.
# Não é mais necessário salvar, localizar ou reler um arquivo CSV.
output.print_md("**Coordenadas e rotação mantidas em memória:** IFC -> Revit.")
output.print_md("**Rotação:** eixo físico da geometria IFC comparado ao eixo físico da família Revit.")

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


def pontos_geometria_instancia(instancia):
    """
    Lê a geometria da FamilyInstance no sistema de coordenadas
    do projeto Revit.
    """
    pontos = []

    try:
        opcoes = Options()
        opcoes.ComputeReferences = False
        geometria = instancia.get_Geometry(opcoes)
    except Exception:
        return pontos

    def coletar(geometria_atual):
        try:
            for geometria_obj in geometria_atual:

                if isinstance(geometria_obj, GeometryInstance):
                    try:
                        coletar(geometria_obj.GetInstanceGeometry())
                    except Exception:
                        try:
                            coletar(geometria_obj.GetSymbolGeometry())
                        except Exception:
                            pass
                    continue

                try:
                    for aresta in geometria_obj.Edges:
                        try:
                            for ponto in aresta.AsCurve().Tessellate():
                                pontos.append(ponto)
                        except Exception:
                            pass
                    continue
                except Exception:
                    pass

                try:
                    for vertice in geometria_obj.Vertices:
                        pontos.append(vertice)
                    continue
                except Exception:
                    pass

                try:
                    for ponto in geometria_obj.GetCoordinates():
                        pontos.append(ponto)
                except Exception:
                    pass

        except Exception:
            pass

    try:
        coletar(geometria)
    except Exception:
        pass

    return pontos


def eixo_fisico_familia(instancia):
    """
    Descobre a direção física principal da família pela geometria.

    O PCA identifica o eixo longitudinal da luminária.
    O HandOrientation/FacingOrientation serve apenas para decidir
    o sentido positivo desse eixo, pois PCA não diferencia
    esquerda/direita.
    """
    pontos = pontos_geometria_instancia(instancia)
    eixo = eixo_principal_xy(pontos)

    if eixo is None:
        # Família quadrada/circular ou geometria insuficiente.
        return None

    candidatos = []

    try:
        vetor = XYZ(
            instancia.HandOrientation.X,
            instancia.HandOrientation.Y,
            0.0
        )
        if vetor.GetLength() > 0.000001:
            candidatos.append(vetor.Normalize())
    except Exception:
        pass

    try:
        vetor = XYZ(
            instancia.FacingOrientation.X,
            instancia.FacingOrientation.Y,
            0.0
        )
        if vetor.GetLength() > 0.000001:
            candidatos.append(vetor.Normalize())
    except Exception:
        pass

    if candidatos:
        melhor = max(
            candidatos,
            key=lambda candidato: abs(eixo.DotProduct(candidato))
        )

        if eixo.DotProduct(melhor) < 0.0:
            eixo = XYZ(
                -eixo.X,
                -eixo.Y,
                0.0
            )

    return eixo.Normalize()


def angulo_normalizado(angulo):
    while angulo > math.pi:
        angulo -= 2.0 * math.pi
    while angulo < -math.pi:
        angulo += 2.0 * math.pi
    return angulo


def rotacionar_instancia(instancia, objeto):
    """
    Alinha a DIREÇÃO FÍSICA da família Revit com a DIREÇÃO FÍSICA
    da luminária IFC.

    Não usa +90, -90 ou +180 fixos.

    Se o IFC aponta para X e a família aponta para -X:
        delta = 180 graus.

    Se o IFC aponta para Y e a família aponta para X:
        delta = 90 graus.

    O eixo físico é obtido da geometria da família, o que corrige
    famílias criadas com origem/eixo interno diferentes.
    """

    ponto = objeto.get("ponto")

    if ponto is None:
        return

    alvo = objeto.get("vetor_direcao")

    if alvo is None:
        angulo = objeto.get("angulo", 0.0)
        alvo = XYZ(
            math.cos(angulo),
            math.sin(angulo),
            0.0
        )

    alvo = XYZ(alvo.X, alvo.Y, 0.0)

    if alvo.GetLength() <= 0.000001:
        return

    alvo = alvo.Normalize()

    atual = eixo_fisico_familia(instancia)

    # Se a geometria não permite descobrir um eixo físico,
    # usa a orientação da própria instância como fallback.
    if atual is None:
        try:
            atual = XYZ(
                instancia.HandOrientation.X,
                instancia.HandOrientation.Y,
                0.0
            )
            if atual.GetLength() > 0.000001:
                atual = atual.Normalize()
            else:
                atual = None
        except Exception:
            atual = None

    if atual is None:
        try:
            atual = XYZ(
                instancia.FacingOrientation.X,
                instancia.FacingOrientation.Y,
                0.0
            )
            if atual.GetLength() > 0.000001:
                atual = atual.Normalize()
            else:
                atual = None
        except Exception:
            atual = None

    if atual is None:
        return

    angulo_alvo = math.atan2(
        alvo.Y,
        alvo.X
    )

    angulo_atual = math.atan2(
        atual.Y,
        atual.X
    )

    delta = angulo_normalizado(
        angulo_alvo - angulo_atual
    )

    if abs(delta) <= 0.000001:
        return

    eixo_z = XYZ.BasisZ

    eixo = Line.CreateBound(
        ponto,
        ponto + eixo_z
    )

    try:
        localizacao = instancia.Location

        if isinstance(localizacao, LocationPoint):
            if localizacao.Rotate(eixo, delta):
                return
    except Exception:
        pass

    ElementTransformUtils.RotateElement(
        revit.doc,
        instancia.Id,
        eixo,
        delta
    )


def centralizar_instancia_no_ponto(instancia, ponto_alvo):
    """
    Depois da rotação, faz o centro geométrico real da família
    coincidir com o centro da luminária IFC.

    Não depende de a origem interna da família estar no centro.
    """

    pontos = pontos_geometria_instancia(instancia)

    centro_familia = centro_geometria_pontos(pontos)

    if centro_familia is None:
        try:
            caixa = instancia.get_BoundingBox(None)
            if caixa is not None:
                centro_familia = (
                    caixa.Min + caixa.Max
                ) * 0.5
        except Exception:
            pass

    if centro_familia is None:
        return False

    deslocamento = ponto_alvo - centro_familia

    if deslocamento.GetLength() <= 0.000001:
        return True

    ElementTransformUtils.MoveElement(
        revit.doc,
        instancia.Id,
        deslocamento
    )

    return True


class TelaCarregamento(Window):
    def __init__(self, total):
        self.Title = "Carregando luminárias"
        self.Width = 520
        self.Height = 280
        self.WindowStartupLocation = WindowStartupLocation.CenterScreen
        self.ResizeMode = ResizeMode.NoResize
        self.Topmost = True

        grid = Grid()
        grid.Margin = Thickness(18)

        for _ in range(4):
            row = RowDefinition()
            row.Height = GridLength(1, GridUnitType.Auto)
            grid.RowDefinitions.Add(row)

        titulo = TextBlock()
        titulo.Text = "Carregando luminárias..."
        titulo.FontSize = 20
        titulo.FontWeight = FontWeights.Bold
        titulo.Margin = Thickness(0, 0, 0, 12)
        Grid.SetRow(titulo, 0)
        grid.Children.Add(titulo)

        self.status = TextBlock()
        self.status.Text = "Preparando inserção..."
        self.status.TextWrapping = TextWrapping.Wrap
        self.status.Margin = Thickness(0, 0, 0, 12)
        Grid.SetRow(self.status, 1)
        grid.Children.Add(self.status)

        self.progress = ProgressBar()
        self.progress.Minimum = 0
        self.progress.Maximum = total
        self.progress.Height = 18
        self.progress.Margin = Thickness(0, 0, 0, 8)
        Grid.SetRow(self.progress, 2)
        grid.Children.Add(self.progress)

        self.lista = ListBox()
        self.lista.Height = 90
        self.lista.Margin = Thickness(0, 8, 0, 0)
        Grid.SetRow(self.lista, 3)
        grid.Children.Add(self.lista)

        self.Content = grid

    def atualizar(self, atual, texto, tipos):
        self.progress.Value = atual
        self.status.Text = texto

        self.lista.Items.Clear()
        for tipo in sorted(set(tipos)):
            self.lista.Items.Add(tipo)

        self.UpdateLayout()


# ETAPA 10 - Insere diretamente no Revit as luminarias mapeadas.
criadas = 0
tipos_carregados = []
niveis = list(
    FilteredElementCollector(revit.doc)
    .OfClass(Level)
    .ToElements()
)
total_para_inserir = len(para_inserir)
intervalo_insercao = 0.30
output.print_md("**Intervalo entre insercoes:** {} segundo(s)".format(
    intervalo_insercao
))

janela_carregamento = None
if para_inserir:
    janela_carregamento = TelaCarregamento(total_para_inserir)
    janela_carregamento.Show()

    for indice, (objeto, simbolo) in enumerate(para_inserir, 1):
        try:
            nome_tipo = camada_luminaria(objeto["tipo"] or objeto["nome"] or "") or objeto["nome"]
            output.print_md(
                "- Inserindo {}/{}: {}".format(
                    indice, total_para_inserir, objeto["nome"]
                )
            )
            if janela_carregamento is not None:
                janela_carregamento.atualizar(
                    indice,
                    "Inserindo {} de {}: {}".format(
                        indice, total_para_inserir, objeto["nome"]
                    ),
                    tipos_carregados
                )

            with revit.Transaction(
                    "Inserir luminaria {}/{}".format(
                        indice, total_para_inserir
                    )):
                if not simbolo.IsActive:
                    simbolo.Activate()
                    revit.doc.Regenerate()
                instancia = inserir_luminaria(objeto, simbolo, niveis)

                # 1. Corrige a orientação física da família.
                rotacionar_instancia(instancia, objeto)
                revit.doc.Regenerate()

                # 2. Agora que a família está na orientação final,
                #    coloca o centro geométrico dela no centro IFC.
                if not centralizar_instancia_no_ponto(
                        instancia,
                        objeto["ponto"]):
                    raise Exception(
                        "Nao foi possivel localizar o centro geometrico "
                        "da familia para alinhar ao IFC."
                    )

                revit.doc.Regenerate()

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
            if nome_tipo not in tipos_carregados:
                tipos_carregados.append(nome_tipo)
            if intervalo_insercao > 0.0 and indice < total_para_inserir:
                time.sleep(intervalo_insercao)
        except Exception as erro:
            objeto["status"] = "NAO ALOCADA - {}".format(erro)
            erros_insercao.append(
                "{}: {}".format(objeto["nome"], erro)
            )

    if janela_carregamento is not None:
        janela_carregamento.Close()

if tipos_carregados:
    lista_tipos = "\n- ".join(tipos_carregados)
    forms.alert(
        "Carregado com sucesso",
        title="Carregamento concluído"
    )
else:
    forms.alert(
        "Carregado com sucesso",
        title="Carregamento concluído"
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


