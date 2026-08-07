"""
streamlit_app.py — Medal Play Tournament App (Las Cruces)
Streamlit + Supabase — formato medal, compatible con HDC importar ronda
"""
import streamlit as st
import random
import string
import uuid
from datetime import date

from supabase import create_client

st.set_page_config(page_title="⛳ Medal Play", layout="centered")

st.markdown("""
<style>
h1 { font-size: 1.4rem !important; }
h2 { font-size: 1.2rem !important; }
h3 { font-size: 1rem !important; }
div[data-testid="stButton"] > button[kind="primary"] {
    width: 100%;
    font-size: 1.1rem;
    padding: 0.6rem;
}
</style>
""", unsafe_allow_html=True)

# ── Supabase ───────────────────────────────────────────────────────────────────

def get_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def get_authed_client():
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        client.auth.set_session(access_token, refresh_token)
        return client
    return get_client()

# ── Auth ───────────────────────────────────────────────────────────────────────

def try_restore_session():
    if st.session_state.get("admin_logged_in"):
        return
    rt = st.session_state.get("refresh_token") or st.query_params.get("_rt")
    if not rt:
        return
    try:
        sb = get_client()
        res = sb.auth.refresh_session(rt)
        if res.session:
            st.session_state["admin_logged_in"] = True
            st.session_state["access_token"] = res.session.access_token
            st.session_state["refresh_token"] = res.session.refresh_token
            st.query_params["_rt"] = res.session.refresh_token
    except Exception:
        st.query_params.pop("_rt", None)

def admin_login():
    try_restore_session()
    if st.session_state.get("admin_logged_in"):
        st.rerun()
        return
    st.title("🔐 Admin")
    email = st.text_input("Email")
    password = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        try:
            sb = get_client()
            res = sb.auth.sign_in_with_password({"email": email, "password": password})
            if res.session:
                st.session_state["admin_logged_in"] = True
                st.session_state["access_token"] = res.session.access_token
                st.session_state["refresh_token"] = res.session.refresh_token
                st.query_params["_rt"] = res.session.refresh_token
                st.rerun()
        except Exception as e:
            st.error("Error: " + str(e))
    st.stop()

# ── Helpers ────────────────────────────────────────────────────────────────────

def rnd_code(n=6):
    return "".join(random.choices(string.digits, k=n))

def rnd_id():
    return str(uuid.uuid4())

# ── DB helpers ─────────────────────────────────────────────────────────────────

DEFAULT_COURSE = "Las Cruces"
DEFAULT_TEE    = "Blancas"

def get_courses():
    sb = get_authed_client()
    return (sb.table("courses").select("id, name").order("name").execute()).data or []

def get_tees(course_id):
    sb = get_authed_client()
    return (sb.table("tees").select("id, color, rating, slope, par").eq("course_id", course_id).execute()).data or []

def get_holes(course_id):
    sb = get_authed_client()
    return (sb.table("holes").select("hole_number, par, handicap").eq("course_id", course_id).order("hole_number").execute()).data or []

def get_players():
    sb = get_authed_client()
    return (sb.table("players").select("id, name, current_handicap").order("name").execute()).data or []

def get_tournaments():
    sb = get_authed_client()
    return (sb.table("tournaments").select("id, name, date, tee_id, access_code").eq("format", "medal").order("date", desc=True).execute()).data or []

def create_tournament(name, date_str, tee_id):
    sb = get_authed_client()
    res = sb.table("tournaments").insert({
        "name": name,
        "date": date_str,
        "tee_id": tee_id,
        "format": "medal",
        "access_code": rnd_code(),
    }).execute()
    return res.data[0] if res.data else None

def delete_tournament(tid):
    sb = get_authed_client()
    groups = sb.table("groups").select("id").eq("tournament_id", tid).execute().data or []
    for g in groups:
        sb.table("group_players").delete().eq("group_id", g["id"]).execute()
        sb.table("tournament_scores").delete().eq("group_id", g["id"]).execute()
    sb.table("groups").delete().eq("tournament_id", tid).execute()
    sb.table("tournaments").delete().eq("id", tid).execute()

def get_groups(tid):
    sb = get_authed_client()
    return (sb.table("groups").select("id, name, access_code").eq("tournament_id", tid).execute()).data or []

def create_group(tid, name):
    sb = get_authed_client()
    res = sb.table("groups").insert({
        "tournament_id": tid,
        "name": name,
        "access_code": rnd_code(),
    }).execute()
    return res.data[0] if res.data else None

def get_group_players(gid):
    sb = get_authed_client()
    return (sb.table("group_players").select("id, player_id, guest_id, player_name, course_handicap").eq("group_id", gid).execute()).data or []

def add_player_to_group(gid, player_name, course_handicap, player_id=None):
    sb = get_authed_client()
    row = {
        "group_id": gid,
        "player_name": player_name,
        "course_handicap": course_handicap,
        "pair_name": "",
        "pair_order": 0,
    }
    if player_id:
        row["player_id"] = player_id
    sb.table("group_players").insert(row).execute()

def remove_player_from_group(gp_id):
    sb = get_authed_client()
    sb.table("group_players").delete().eq("id", gp_id).execute()

def upsert_score(tid, gid, hole_number, strokes, player_id=None, guest_id=None):
    sb = get_authed_client()
    q = sb.table("tournament_scores").select("id").eq("tournament_id", tid).eq("hole_number", hole_number)
    if player_id:
        q = q.eq("player_id", player_id)
    elif guest_id:
        q = q.eq("guest_id", guest_id)
    existing = q.execute().data

    row = {
        "tournament_id": tid,
        "hole_number": hole_number,
        "strokes": strokes,
        "net_strokes": strokes,
        "group_id": gid,
        "pair_name": "",
    }
    if player_id:
        row["player_id"] = player_id
    if guest_id:
        row["guest_id"] = guest_id

    if existing:
        sb.table("tournament_scores").update(row).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("tournament_scores").insert(row).execute()

def get_scores(tid):
    sb = get_authed_client()
    return (sb.table("tournament_scores").select("player_id, guest_id, hole_number, strokes").eq("tournament_id", tid).execute()).data or []

# ══════════════════════════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
    st.title("⛳ Medal Play — Las Cruces")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ Nuevo Torneo", type="primary", use_container_width=True):
            st.session_state["page"] = "nuevo_torneo"
            st.rerun()
    with col2:
        if st.button("📋 Torneos", use_container_width=True):
            st.session_state["page"] = "torneos"
            st.rerun()

    st.markdown("---")
    # Acceso rápido por código de grupo
    st.subheader("Acceso rápido")
    code = st.text_input("Código de grupo", placeholder="123456", max_chars=6)
    if st.button("Entrar al grupo", use_container_width=True):
        if code:
            sb = get_client()
            res = sb.table("groups").select("id, name, access_code, tournament_id").eq("access_code", code).execute()
            if res.data:
                g = res.data[0]
                st.session_state["page"] = "capturar"
                st.session_state["group_id"] = g["id"]
                st.session_state["group_name"] = g["name"]
                st.session_state["tournament_id"] = g["tournament_id"]
                st.rerun()
            else:
                st.error("Código no encontrado.")

def page_nuevo_torneo():
    admin_login()
    st.title("➕ Nuevo Torneo Medal")

    courses = get_courses()
    if not courses:
        st.error("No hay campos en la base de datos.")
        return

    course_opts = {c["name"]: c for c in courses}
    default_idx = list(course_opts.keys()).index(DEFAULT_COURSE) if DEFAULT_COURSE in course_opts else 0
    sel_course = st.selectbox("Campo", list(course_opts.keys()), index=default_idx)
    course = course_opts[sel_course]

    tees = get_tees(course["id"])
    if not tees:
        st.warning("No hay tees para este campo.")
        return
    tee_opts = {t["color"]: t for t in tees}
    default_tee_idx = list(tee_opts.keys()).index(DEFAULT_TEE) if DEFAULT_TEE in tee_opts else 0
    sel_tee = st.selectbox("Tees", list(tee_opts.keys()), index=default_tee_idx)
    tee = tee_opts[sel_tee]

    nombre = st.text_input("Nombre del torneo", placeholder="Medal 07-Ago")
    fecha  = st.date_input("Fecha", value=date.today())

    if st.button("Crear Torneo", type="primary", use_container_width=True):
        if not nombre.strip():
            st.error("Ponle nombre al torneo.")
            return
        torneo = create_tournament(nombre.strip(), str(fecha), tee["id"])
        if torneo:
            st.success("Torneo creado ✅")
            st.session_state["page"] = "torneo_detail"
            st.session_state["tournament_id"] = torneo["id"]
            st.rerun()
        else:
            st.error("Error al crear el torneo.")

    if st.button("← Atrás", use_container_width=True):
        st.session_state["page"] = "home"
        st.rerun()

def page_torneos():
    admin_login()
    st.title("📋 Torneos Medal")

    torneos = get_tournaments()
    if not torneos:
        st.info("No hay torneos medal.")
    else:
        for t in torneos:
            col1, col2, col3 = st.columns([4, 2, 1])
            with col1:
                if st.button(str(t["date"]) + " — " + t["name"], key="t_" + t["id"], use_container_width=True):
                    st.session_state["page"] = "torneo_detail"
                    st.session_state["tournament_id"] = t["id"]
                    st.rerun()
            with col2:
                st.caption("Código: " + str(t.get("access_code", "")))
            with col3:
                if st.button("🗑", key="del_" + t["id"]):
                    delete_tournament(t["id"])
                    st.rerun()

    if st.button("← Atrás", use_container_width=True):
        st.session_state["page"] = "home"
        st.rerun()

def page_torneo_detail():
    admin_login()
    tid = st.session_state.get("tournament_id")
    if not tid:
        st.session_state["page"] = "torneos"
        st.rerun()
        return

    torneos = get_tournaments()
    torneo = next((t for t in torneos if t["id"] == tid), None)
    if not torneo:
        st.error("Torneo no encontrado.")
        return

    st.title("⛳ " + torneo["name"])
    st.caption(str(torneo["date"]) + " | Código admin: " + str(torneo.get("access_code", "")))

    groups = get_groups(tid)

    # Crear grupo
    with st.expander("➕ Agregar grupo"):
        gname = st.text_input("Nombre del grupo", key="new_group_name")
        if st.button("Crear grupo", key="btn_new_group", type="primary"):
            if gname.strip():
                create_group(tid, gname.strip())
                st.rerun()

    st.markdown("---")

    # Lista de grupos
    players_hdc = get_players()
    phdc_opts = {p["name"]: p for p in players_hdc}

    for grp in groups:
        st.subheader("👥 " + grp["name"] + "  |  Código: " + grp["access_code"])
        gps = get_group_players(grp["id"])

        for gp in gps:
            col1, col2 = st.columns([5, 1])
            with col1:
                st.write("• " + str(gp["player_name"]) + "  (HC: " + str(gp.get("course_handicap", "-")) + ")")
            with col2:
                if st.button("✖", key="rm_" + gp["id"]):
                    remove_player_from_group(gp["id"])
                    st.rerun()

        with st.expander("Agregar jugador al grupo"):
            col_a, col_b = st.columns(2)
            with col_a:
                sel_p = st.selectbox("Jugador HDC", ["(invitado)"] + list(phdc_opts.keys()), key="sp_" + grp["id"])
            with col_b:
                hcp_input = st.number_input("Course HC", min_value=0, max_value=54, value=0, key="hc_" + grp["id"])
            if sel_p != "(invitado)":
                pdata = phdc_opts[sel_p]
                if st.button("Agregar", key="add_" + grp["id"], type="primary"):
                    add_player_to_group(grp["id"], pdata["name"], hcp_input, player_id=pdata["id"])
                    st.rerun()
            else:
                guest_name = st.text_input("Nombre invitado", key="gn_" + grp["id"])
                if st.button("Agregar invitado", key="addi_" + grp["id"], type="primary"):
                    if guest_name.strip():
                        add_player_to_group(grp["id"], guest_name.strip(), hcp_input)
                        st.rerun()

        if st.button("📝 Capturar scores — " + grp["name"], key="cap_" + grp["id"], use_container_width=True):
            st.session_state["page"] = "capturar"
            st.session_state["group_id"] = grp["id"]
            st.session_state["group_name"] = grp["name"]
            st.rerun()

        st.markdown("---")

    if st.button("← Torneos", use_container_width=True):
        st.session_state["page"] = "torneos"
        st.rerun()

def page_capturar():
    tid = st.session_state.get("tournament_id")
    gid = st.session_state.get("group_id")
    gname = st.session_state.get("group_name", "Grupo")

    if not tid or not gid:
        st.error("No hay torneo/grupo seleccionado.")
        return

    st.title("📝 " + gname)

    gps = get_group_players(gid)
    if not gps:
        st.warning("No hay jugadores en este grupo.")
        return

    # Scores actuales
    scores_raw = get_scores(tid)
    scores_idx = {}
    for s in scores_raw:
        pid = s.get("player_id") or s.get("guest_id")
        scores_idx[(pid, s["hole_number"])] = s["strokes"]

    # Tabla de captura por jugador
    for gp in gps:
        pid = gp.get("player_id") or gp.get("guest_id") or gp["id"]
        st.subheader(gp["player_name"])

        col_labels = st.columns(10)
        col_labels[0].markdown("**Hoyo**")
        for i in range(1, 10):
            col_labels[i].markdown("**" + str(i) + "**")

        # Front 9
        front_vals = []
        cols_f = st.columns(10)
        cols_f[0].markdown("Front")
        for i, h in enumerate(range(1, 10)):
            v = scores_idx.get((pid, h), 0)
            front_vals.append(cols_f[i+1].number_input(
                "", min_value=0, max_value=20, value=int(v),
                key="f_" + str(gp["id"]) + "_" + str(h), label_visibility="collapsed"
            ))

        # Back 9
        back_vals = []
        cols_b = st.columns(10)
        cols_b[0].markdown("Back")
        for i, h in enumerate(range(10, 19)):
            v = scores_idx.get((pid, h), 0)
            back_vals.append(cols_b[i+1].number_input(
                "", min_value=0, max_value=20, value=int(v),
                key="b_" + str(gp["id"]) + "_" + str(h), label_visibility="collapsed"
            ))

        total = sum(front_vals) + sum(back_vals)
        st.caption("Front: " + str(sum(front_vals)) + " | Back: " + str(sum(back_vals)) + " | Total: " + str(total))

        if st.button("💾 Guardar " + gp["player_name"], key="save_" + gp["id"], type="primary", use_container_width=True):
            for i, h in enumerate(range(1, 10)):
                upsert_score(tid, gid, h, int(front_vals[i]),
                             player_id=gp.get("player_id"), guest_id=gp.get("guest_id"))
            for i, h in enumerate(range(10, 19)):
                upsert_score(tid, gid, h, int(back_vals[i]),
                             player_id=gp.get("player_id"), guest_id=gp.get("guest_id"))
            st.success("Scores guardados ✅")

        st.markdown("---")

    if st.button("← Volver al torneo", use_container_width=True):
        st.session_state["page"] = "torneo_detail"
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

page = st.session_state.get("page", "home")

if page == "home":
    page_home()
elif page == "nuevo_torneo":
    page_nuevo_torneo()
elif page == "torneos":
    page_torneos()
elif page == "torneo_detail":
    page_torneo_detail()
elif page == "capturar":
    page_capturar()
else:
    st.session_state["page"] = "home"
    st.rerun()
