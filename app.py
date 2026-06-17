import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from datetime import datetime

from PIL import Image

logo = Image.open("LOGO STOCKAI.png")

st.set_page_config(
    page_title="STOCKAI V9.1",
    page_icon=logo,
    layout="wide"
)

MESES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO","JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

def pesos(v):
    try:
        return f"${float(v):,.0f}".replace(",", ".")
    except Exception:
        return "$0"

def pesos_mm(v):
    try:
        return f"${float(v)/1_000_000:,.0f} MM".replace(",", ".")
    except Exception:
        return "$0 MM"

def numero(v):
    try:
        return f"{float(v):,.0f}".replace(",", ".")
    except Exception:
        return "0"

def pct(v):
    try:
        return f"{float(v):.1%}"
    except Exception:
        return "0.0%"

def normalizar_cliente(x):
    x = str(x).upper().strip()
    x = x.replace("CONSTRUCTORA INGEVOC SA", "CONSTRUCTORA INGEVEC SA")
    x = x.replace("CONSTRUCTORA INGEVOC S.A.", "CONSTRUCTORA INGEVEC SA")
    x = x.replace("CONSTRUCTORA INGEVOC S.A", "CONSTRUCTORA INGEVEC SA")
    x = x.replace("INGEVOC", "INGEVEC")
    return x

def preparar_df(df):
    df.columns = df.columns.astype(str).str.strip().str.upper()
    df = df.rename(columns={
        "DESCRIPCIÓN": "DESCRIPCION",
        "DESCRIPCION": "PRODUCTO",
        "TOTAL UNID": "TOTAL UN",
        "CANAL ESTRATEGICO": "CANAL_ESTRATEGICO",
        "CANAL ESTRATÉGICO": "CANAL_ESTRATEGICO"
    })
    req = ["MES", "CLIENTE", "PRODUCTO", "VALOR TOTAL UNITARIO"]
    faltantes = [c for c in req if c not in df.columns]
    if faltantes:
        st.error(f"Faltan columnas obligatorias: {faltantes}")
        st.write("Columnas encontradas:", list(df.columns))
        st.stop()
    if "TOTAL UN" not in df.columns:
        df["TOTAL UN"] = 0
    if "CANAL" not in df.columns:
        df["CANAL"] = "SIN CANAL"
    if "CANAL_ESTRATEGICO" not in df.columns:
        df["CANAL_ESTRATEGICO"] = "SIN CLASIFICAR"
    df["VALOR TOTAL UNITARIO"] = pd.to_numeric(df["VALOR TOTAL UNITARIO"], errors="coerce").fillna(0)
    df["TOTAL UN"] = pd.to_numeric(df["TOTAL UN"], errors="coerce").fillna(0)
    df["MES"] = df["MES"].astype(str).str.upper().str.strip()
    df["CLIENTE"] = df["CLIENTE"].apply(normalizar_cliente)
    df["PRODUCTO"] = df["PRODUCTO"].astype(str).str.upper().str.strip()
    df["CANAL"] = df["CANAL"].astype(str).str.upper().str.strip()
    df["CANAL_ESTRATEGICO"] = df["CANAL_ESTRATEGICO"].astype(str).str.upper().str.strip()
    return df

def abc(df, col):
    t = df.groupby(col)["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    total = t["VALOR TOTAL UNITARIO"].sum()
    if total <= 0:
        t["% VENTA"] = 0; t["% ACUMULADO"] = 0; t["ABC"] = "C"; return t
    t["% VENTA"] = t["VALOR TOTAL UNITARIO"] / total
    t["% ACUMULADO"] = t["% VENTA"].cumsum()
    t["ABC"] = t["% ACUMULADO"].apply(lambda x: "A" if x <= 0.80 else ("B" if x <= 0.95 else "C"))
    return t

def forecast_mensual(df):
    f = df.groupby("MES")["VALOR TOTAL UNITARIO"].sum().reindex(MESES).fillna(0).reset_index()
    f["CONSERVADOR +5%"] = f["VALOR TOTAL UNITARIO"] * 1.05
    f["REALISTA +10%"] = f["VALOR TOTAL UNITARIO"] * 1.10
    f["AGRESIVO +20%"] = f["VALOR TOTAL UNITARIO"] * 1.20
    return f

def forecast_tabla(df, col):
    t = df.groupby(col)["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    t = t.rename(columns={"VALOR TOTAL UNITARIO": "VENTA 2025"})
    t["FORECAST 2026"] = t["VENTA 2025"] * 1.10
    t["DIFERENCIA"] = t["FORECAST 2026"] - t["VENTA 2025"]
    return t

def tabla_formato(t):
    t = t.copy()
    for c in ["VALOR TOTAL UNITARIO","VENTA 2025","FORECAST 2026","DIFERENCIA","CONSERVADOR +5%","REALISTA +10%","AGRESIVO +20%"]:
        if c in t.columns:
            t[c] = t[c].apply(pesos)
    for c in ["% VENTA","% ACUMULADO","%"]:
        if c in t.columns:
            t[c] = t[c].apply(lambda x: f"{x:.1%}" if isinstance(x,(int,float)) else x)
    return t

def detectar_retail_constructor(df_base):
    total = df_base["VALOR TOTAL UNITARIO"].sum()
    canal = df_base["CANAL"].astype(str).str.upper()
    canal_est = df_base["CANAL_ESTRATEGICO"].astype(str).str.upper()
    cliente = df_base["CLIENTE"].astype(str).str.upper()
    mask_retail = (
        canal.str.contains("RETAIL", na=False) |
        canal.str.contains("MINORISTA", na=False) |
        canal_est.str.contains("CHILEMAT|CONSTRUMART|MTS|IMPERIAL|EASY|RETAIL|FERRETER", na=False)
    )
    mask_constructor = (
        canal.str.contains("CONSTRUCT", na=False) |
        canal_est.str.contains("CONSTRUCT", na=False) |
        cliente.str.contains("CONSTRUCTORA|INGEVEC|ICF|CARRAN", na=False)
    )
    venta_retail = df_base.loc[mask_retail, "VALOR TOTAL UNITARIO"].sum()
    venta_constructor = df_base.loc[mask_constructor, "VALOR TOTAL UNITARIO"].sum()
    return venta_retail, (venta_retail/total if total else 0), venta_constructor, (venta_constructor/total if total else 0)

def generar_pdf(resumen, clientes, productos, forecast):
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
    except Exception:
        st.error("Falta instalar reportlab. Ejecuta en CMD: pip install reportlab")
        return None
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elems = [
        Paragraph("STOCKAI EXECUTIVE REPORT", styles["Title"]),
        Paragraph("Moldecor - Informe Gerencial Automático", styles["Heading2"]),
        Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("Resumen Ejecutivo", styles["Heading2"])
    ]
    for r in resumen:
        elems.append(Paragraph(r, styles["BodyText"]))
    elems.append(Spacer(1,14))
    def add_table(title, df):
        elems.append(Paragraph(title, styles["Heading2"]))
        data = [list(df.columns)] + df.astype(str).values.tolist()
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1E40AF")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),0.25,colors.grey),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),7),
        ]))
        elems.append(table); elems.append(Spacer(1,12))
    add_table("Top 10 Clientes", clientes)
    add_table("Top 10 Productos", productos)
    add_table("Forecast 2026", forecast)
    doc.build(elems)
    buffer.seek(0)
    return buffer

st.title("📊 STOCKAI Executive V9.1")
st.caption("Ventas 2025 • Riesgo Comercial • Forecast 2026 • PDF Ejecutivo")
menu = st.sidebar.radio("📋 Menú", ["Panel Ejecutivo","Ventas Mensuales","Clientes","Productos","Clientes ABC","Productos ABC","Segmento Estratégico","Riesgo Comercial","Advisor IA","Forecast 2026","PDF Ejecutivo"])
archivo = st.file_uploader("Sube el Excel de ventas 2025", type=["xlsx"])
if archivo is None:
    st.info("Sube el Excel para comenzar.")
    st.stop()

df0 = preparar_df(pd.read_excel(archivo, sheet_name="resumen 2025"))
df = df0.copy()
st.sidebar.header("🔎 Filtros")
canal = st.sidebar.selectbox("Canal", ["Todos"] + sorted(df["CANAL"].dropna().unique()))
if canal != "Todos": df = df[df["CANAL"] == canal]
canal_est = st.sidebar.selectbox("Canal Estratégico", ["Todos"] + sorted(df["CANAL_ESTRATEGICO"].dropna().unique()))
if canal_est != "Todos": df = df[df["CANAL_ESTRATEGICO"] == canal_est]
cliente = st.sidebar.selectbox("Cliente", ["Todos"] + sorted(df["CLIENTE"].dropna().unique()))
if cliente != "Todos": df = df[df["CLIENTE"] == cliente]
producto = st.sidebar.selectbox("Producto", ["Todos"] + sorted(df["PRODUCTO"].dropna().unique()))
if producto != "Todos": df = df[df["PRODUCTO"] == producto]

venta_empresa = df0["VALOR TOTAL UNITARIO"].sum()
venta_vista = df["VALOR TOTAL UNITARIO"].sum()
c1,c2,c3,c4 = st.columns(4)
c1.metric("💰 Venta Empresa", pesos_mm(venta_empresa))
c2.metric("🔎 Venta Vista", pesos_mm(venta_vista))
c3.metric("👥 Clientes", numero(df["CLIENTE"].nunique()))
c4.metric("📦 Productos", numero(df["PRODUCTO"].nunique()))
st.caption(f"Venta empresa exacta: {pesos(venta_empresa)} | Venta vista exacta: {pesos(venta_vista)}")
st.divider()
if venta_vista <= 0:
    st.warning("La vista actual no tiene ventas. Ajusta los filtros.")
    st.stop()

if menu == "Panel Ejecutivo":
    st.subheader("📋 Resumen Ejecutivo")
    clientes = df.groupby("CLIENTE")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    productos = df.groupby("PRODUCTO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    meses = df.groupby("MES")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    segmentos = df.groupby("CANAL_ESTRATEGICO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    a,b,c,d = st.columns(4)
    a.success(f"🏆 Cliente líder\n\n{clientes.index[0]}\n\n{pesos(clientes.iloc[0])}")
    b.info(f"📦 Producto líder\n\n{productos.index[0]}\n\n{pesos(productos.iloc[0])}")
    c.warning(f"📈 Mejor mes\n\n{meses.index[0]}\n\n{pesos(meses.iloc[0])}")
    d.success(f"🏪 Canal líder\n\n{segmentos.index[0]}\n\n{pesos(segmentos.iloc[0])}")
    st.subheader("🏗️ Peso Retail vs Constructoras en el Negocio")
    vr, pr, vc, pc = detectar_retail_constructor(df0)
    r1, r2 = st.columns(2)
    r1.metric("🛒 Total Retail", pesos_mm(vr), pct(pr))
    r2.metric("🏗️ Total Constructoras", pesos_mm(vc), pct(pc))
    mix = pd.DataFrame({"SEGMENTO":["RETAIL","CONSTRUCTORAS","OTROS"],"VENTA":[vr, vc, max(venta_empresa-vr-vc,0)]})
    mix["% NEGOCIO"] = mix["VENTA"] / venta_empresa
    fig_mix = px.bar(mix, x="SEGMENTO", y="VENTA", text="VENTA", title="Composición del negocio por macrosegmento")
    fig_mix.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig_mix.update_layout(height=450, yaxis_tickprefix="$")
    st.plotly_chart(fig_mix, use_container_width=True)
    mt = mix.copy(); mt["VENTA"] = mt["VENTA"].apply(pesos); mt["% NEGOCIO"] = mt["% NEGOCIO"].apply(lambda x: f"{x:.1%}")
    st.dataframe(mt, use_container_width=True)
    vm = df.groupby("MES")["VALOR TOTAL UNITARIO"].sum().reindex(MESES).fillna(0).reset_index()
    fig = px.bar(vm, x="MES", y="VALOR TOTAL UNITARIO", text="VALOR TOTAL UNITARIO", title="Ventas por Mes")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=540, yaxis_tickprefix="$")
    st.plotly_chart(fig, use_container_width=True)
elif menu == "Ventas Mensuales":
    vm = df.groupby("MES")["VALOR TOTAL UNITARIO"].sum().reindex(MESES).fillna(0).reset_index()
    fig = px.bar(vm, x="MES", y="VALOR TOTAL UNITARIO", text="VALOR TOTAL UNITARIO", title="Ventas Mensuales")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=540, yaxis_tickprefix="$")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(tabla_formato(vm), use_container_width=True)
elif menu == "Clientes":
    r = df.groupby("CLIENTE")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    fig = px.bar(r.head(20), x="VALOR TOTAL UNITARIO", y="CLIENTE", orientation="h", text="VALOR TOTAL UNITARIO", title="Top 20 Clientes")
    fig.update_yaxes(categoryorder="total ascending")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=700, xaxis_tickprefix="$", margin=dict(l=20,r=180,t=60,b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(tabla_formato(r), use_container_width=True)
elif menu == "Productos":
    r = df.groupby("PRODUCTO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    fig = px.bar(r.head(20), x="VALOR TOTAL UNITARIO", y="PRODUCTO", orientation="h", text="VALOR TOTAL UNITARIO", title="Top 20 Productos")
    fig.update_yaxes(categoryorder="total ascending")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=700, xaxis_tickprefix="$", margin=dict(l=20,r=180,t=60,b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(tabla_formato(r), use_container_width=True)
elif menu == "Clientes ABC":
    t = abc(df, "CLIENTE")
    a,b,c = st.columns(3)
    a.success(f"Clientes A\n\n{len(t[t['ABC']=='A'])}")
    b.warning(f"Clientes B\n\n{len(t[t['ABC']=='B'])}")
    c.error(f"Clientes C\n\n{len(t[t['ABC']=='C'])}")
    st.dataframe(tabla_formato(t), use_container_width=True)
elif menu == "Productos ABC":
    t = abc(df, "PRODUCTO")
    a,b,c = st.columns(3)
    a.success(f"Productos A\n\n{len(t[t['ABC']=='A'])}")
    b.warning(f"Productos B\n\n{len(t[t['ABC']=='B'])}")
    c.error(f"Productos C\n\n{len(t[t['ABC']=='C'])}")
    st.dataframe(tabla_formato(t), use_container_width=True)
elif menu == "Segmento Estratégico":
    r = df.groupby("CANAL_ESTRATEGICO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    r["%"] = r["VALOR TOTAL UNITARIO"] / r["VALOR TOTAL UNITARIO"].sum()
    fig = px.bar(r, x="VALOR TOTAL UNITARIO", y="CANAL_ESTRATEGICO", orientation="h", text="VALOR TOTAL UNITARIO", title="Canal Estratégico")
    fig.update_yaxes(categoryorder="total ascending")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=560, xaxis_tickprefix="$", margin=dict(l=20,r=180,t=60,b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(tabla_formato(r), use_container_width=True)
elif menu == "Riesgo Comercial":
    clientes = df.groupby("CLIENTE")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    productos = df.groupby("PRODUCTO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    total = df["VALOR TOTAL UNITARIO"].sum()
    top_cliente = clientes.iloc[0]["VALOR TOTAL UNITARIO"] / total
    top5 = clientes.head(5)["VALOR TOTAL UNITARIO"].sum() / total
    top10 = clientes.head(10)["VALOR TOTAL UNITARIO"].sum() / total
    top10p = productos.head(10)["VALOR TOTAL UNITARIO"].sum() / total
    a,b,c,d = st.columns(4)
    a.metric("Top Cliente", f"{top_cliente:.1%}")
    b.metric("Top 5 Clientes", f"{top5:.1%}")
    c.metric("Top 10 Clientes", f"{top10:.1%}")
    d.metric("Top 10 Productos", f"{top10p:.1%}")
    if top_cliente >= 0.25: st.error(f"🔴 Riesgo alto: {clientes.iloc[0]['CLIENTE']} concentra {top_cliente:.1%}.")
    elif top_cliente >= 0.15: st.warning(f"🟡 Riesgo medio: {clientes.iloc[0]['CLIENTE']} concentra {top_cliente:.1%}.")
    else: st.success("🟢 Riesgo cliente controlado.")
    clientes["%"] = clientes["VALOR TOTAL UNITARIO"] / total
    productos["%"] = productos["VALOR TOTAL UNITARIO"] / total
    st.write("### Clientes con mayor dependencia")
    st.dataframe(tabla_formato(clientes.head(10)), use_container_width=True)
    st.write("### Productos con mayor dependencia")
    st.dataframe(tabla_formato(productos.head(10)), use_container_width=True)
elif menu == "Advisor IA":
    clientes = df.groupby("CLIENTE")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    productos = df.groupby("PRODUCTO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    meses = df.groupby("MES")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    segmentos = df.groupby("CANAL_ESTRATEGICO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False)
    ac = abc(df, "CLIENTE"); ap = abc(df, "PRODUCTO")
    total = df["VALOR TOTAL UNITARIO"].sum(); pcli = clientes.iloc[0] / total
    vr, pr, vc, pc = detectar_retail_constructor(df0)
    st.markdown(f'''### 📢 Resumen Ejecutivo Automático

- **Venta analizada:** {pesos(total)}
- **Cliente líder:** {clientes.index[0]} ({pcli:.1%} de participación)
- **Producto líder:** {productos.index[0]}
- **Canal estratégico líder:** {segmentos.index[0]}
- **Mejor mes:** {meses.index[0]}
- **Retail total empresa:** {pesos(vr)} ({pr:.1%} del negocio)
- **Constructoras total empresa:** {pesos(vc)} ({pc:.1%} del negocio)
- **Clientes A:** {len(ac[ac["ABC"]=="A"])} clientes generan cerca del 80% de la venta.
- **Productos A:** {len(ap[ap["ABC"]=="A"])} productos generan cerca del 80% de la venta.
''')
    st.info("💡 Recomendación: potenciar clientes B, reducir dependencia del cliente líder y revisar productos C.")
elif menu == "Forecast 2026":
    f = forecast_mensual(df); venta_2025 = f["VALOR TOTAL UNITARIO"].sum(); forecast_2026 = f["REALISTA +10%"].sum()
    a,b,c = st.columns(3)
    a.metric("Venta 2025", pesos_mm(venta_2025)); b.metric("Forecast 2026 Realista", pesos_mm(forecast_2026)); c.metric("Crecimiento esperado", pesos_mm(forecast_2026 - venta_2025))
    graf = f[["MES","VALOR TOTAL UNITARIO","REALISTA +10%"]].rename(columns={"VALOR TOTAL UNITARIO":"VENTA 2025"})
    gm = graf.melt(id_vars="MES", var_name="ESCENARIO", value_name="VENTA")
    fig = px.bar(gm, x="MES", y="VENTA", color="ESCENARIO", barmode="group", text="VENTA", title="Venta 2025 vs Forecast 2026")
    fig.update_traces(texttemplate="$%{text:,.0f}", textposition="outside", cliponaxis=False)
    fig.update_layout(height=600, yaxis_tickprefix="$")
    st.plotly_chart(fig, use_container_width=True)
    st.subheader("📊 Escenarios 2026")
    st.dataframe(tabla_formato(f.rename(columns={"VALOR TOTAL UNITARIO":"VENTA 2025"})), use_container_width=True)
    st.subheader("🏆 Forecast por Cliente")
    st.dataframe(tabla_formato(forecast_tabla(df, "CLIENTE").head(20)), use_container_width=True)
    st.subheader("📦 Forecast por Producto")
    st.dataframe(tabla_formato(forecast_tabla(df, "PRODUCTO").head(20)), use_container_width=True)
    st.subheader("🏪 Forecast por Canal Estratégico")
    st.dataframe(tabla_formato(forecast_tabla(df, "CANAL_ESTRATEGICO")), use_container_width=True)
elif menu == "PDF Ejecutivo":
    st.subheader("📄 Informe Ejecutivo PDF")
    clientes = df.groupby("CLIENTE")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    productos = df.groupby("PRODUCTO")["VALOR TOTAL UNITARIO"].sum().sort_values(ascending=False).reset_index()
    f = forecast_mensual(df); venta_2025 = f["VALOR TOTAL UNITARIO"].sum(); forecast_2026 = f["REALISTA +10%"].sum()
    vr, pr, vc, pc = detectar_retail_constructor(df0)
    resumen = [
        f"Venta 2025 analizada: {pesos(venta_2025)}",
        f"Forecast 2026 realista: {pesos(forecast_2026)}",
        f"Crecimiento esperado: {pesos(forecast_2026 - venta_2025)}",
        f"Retail total empresa: {pesos(vr)} ({pr:.1%} del negocio)",
        f"Constructoras total empresa: {pesos(vc)} ({pc:.1%} del negocio)",
        f"Cliente lider: {clientes.iloc[0]['CLIENTE']} con {pesos(clientes.iloc[0]['VALOR TOTAL UNITARIO'])}",
        f"Producto lider: {productos.iloc[0]['PRODUCTO']} con {pesos(productos.iloc[0]['VALOR TOTAL UNITARIO'])}",
        "Recomendacion: potenciar clientes B, revisar productos C y monitorear dependencia comercial."
    ]
    st.markdown("### Vista previa")
    for r in resumen: st.write("• " + r)
    tc = clientes.head(10).copy(); tc["VALOR TOTAL UNITARIO"] = tc["VALOR TOTAL UNITARIO"].apply(pesos)
    tp = productos.head(10).copy(); tp["VALOR TOTAL UNITARIO"] = tp["VALOR TOTAL UNITARIO"].apply(pesos)
    fp = f.rename(columns={"VALOR TOTAL UNITARIO":"VENTA 2025"})
    fp = tabla_formato(fp[["MES","VENTA 2025","CONSERVADOR +5%","REALISTA +10%","AGRESIVO +20%"]])
    pdf = generar_pdf(resumen, tc, tp, fp)
    if pdf is not None:
        st.download_button("⬇ Descargar PDF Ejecutivo", data=pdf, file_name="STOCKAI_EXECUTIVE_REPORT.pdf", mime="application/pdf")
