"""
streamlit_app.py — Medal Play Tournament App (Las Cruces)
Streamlit + Supabase — formato medal, compatible con HDC importar ronda
Diseño similar a Stableford: sidebar + leaderboard
"""
import streamlit as st
import random
import string
import uuid
import pandas as pd
from datetime import date
from collections import defaultdict

from supabase import create_client

st.set_page_config(page_title="⛳ Medal Play", layout="wide")

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
section[data-testid="stSidebar"] { min-width: 200px !important; }
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
    if st.button("Entrar", type="primary", use_container_width=True):
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

DEFAULT_COURSE = "Las Cruces"
DEFAULT_TEE = "Blancas"

# ── DB helpers ─────────────────────────────────────────────────────────────────

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

def get_all_tournament_players(tid):
    groups = get_groups(tid)
    players = []
    for g in groups:
        for p in get_group_players(g["id"]):
            p["group_name"] = g["name"]
            p["group_id"] = g["id"]
            players.append(p)
    return players

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

def get_group_by_code(code):
    sb = get_authed_client()
    res = sb.table("groups").select("id, name, access_code, tournament_id").eq("access_code", code).execute()
    if not res.data:
        return None
    group = res.data[0]
    torneo_res = sb.table("tournaments").select("id, name, date, tee_id, access_code").eq("id", group["tournament_id"]).execute()
    if not torneo_res.data:
        return None
    return {"group": group, "torneo": torneo_res.data[0]}

# ══════════════════════════════════════════════════════════════════════════════
# LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

def leaderboard_ui():
    st.title("⛳ Leaderboard — Medal Play")

    tournaments = get_tournaments()
    if not tournaments:
        st.info("No hay torneos disponibles.")
        return

    t_map = {t['name']: t for t in tournaments}
    t_label = st.selectbox("Torneo", list(t_map.keys()), index=None, placeholder="Selecciona un torneo...")
    if t_label is None:
        st.info("Selecciona un torneo para ver el leaderboard.")
        return

    torneo = t_map[t_label]
    players = get_all_tournament_players(torneo["id"])
    scores_raw = get_scores(torneo["id"])

    if not players:
        st.warning("Este torneo no tiene jugadores.")
        return

    # Índice de scores por (player_id/guest_id, hoyo)
    scores_idx = {}
    for s in scores_raw:
        pid = s.get("player_id") or s.get("guest_id")
        scores_idx[(pid, s["hole_number"])] = s["strokes"]

    # Traer hoyos del campo
    sb = get_authed_client()
    tee_id = torneo.get("tee_id")
    tee = {}
    course_id = None
    if tee_id:
        tee_res = sb.table("tees").select("course_id").eq("id", tee_id).execute()
        tee = tee_res.data[0] if tee_res.data else {}
        course_id = tee.get("course_id")

    holes_list = get_holes(course_id) if course_id else []
    holes = {h["hole_number"]: h for h in holes_list}
    hole_nums = sorted(holes.keys())

    # Calcular totales por jugador
    player_totals = {}
    player_front = {}
    player_back = {}
    for p in players:
        pid = p.get("player_id") or p.get("guest_id")
        front = 0
        back = 0
        for h in range(1, 10):
            v = scores_idx.get((pid, h), 0)
            if v:
                front += v
        for h in range(10, 19):
            v = scores_idx.get((pid, h), 0)
            if v:
                back += v
        player_totals[pid] = front + back
        player_front[pid] = front
        player_back[pid] = back

    # Rankear
    ranked = []
    for p in players:
        pid = p.get("player_id") or p.get("guest_id")
        total = player_totals.get(pid, 0)
        ranked.append({
            "pid": pid,
            "name": p["player_name"],
            "total": total,
            "front": player_front.get(pid, 0),
            "back": player_back.get(pid, 0),
        })
    ranked.sort(key=lambda x: x["total"] if x["total"] > 0 else float('inf'))

    # Ganadores
    st.markdown(f"### 🏆 Ganadores")
    if ranked:
        best_total = min(r["total"] for r in ranked if r["total"] > 0)
        best_front = min(player_front.get((p.get("player_id") or p.get("guest_id")), 0) for p in players if player_front.get((p.get("player_id") or p.get("guest_id")), 0) > 0)
        best_back = min(player_back.get((p.get("player_id") or p.get("guest_id")), 0) for p in players if player_back.get((p.get("player_id") or p.get("guest_id")), 0) > 0)

        winners_total = [r["name"] for r in ranked if r["total"] == best_total]
        winners_front = [p["player_name"] for p in players if player_front.get((p.get("player_id") or p.get("guest_id")), 0) == best_front and best_front > 0]
        winners_back = [p["player_name"] for p in players if player_back.get((p.get("player_id") or p.get("guest_id")), 0) == best_back and best_back > 0]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🌅 Front 9", f"{best_front}", " / ".join(winners_front) if winners_front else "—")
        with col2:
            st.metric("🌆 Back 9", f"{best_back}", " / ".join(winners_back) if winners_back else "—")
        with col3:
            st.metric("🎖️ Torneo", f"{best_total}", " / ".join(winners_total) if winners_total else "—")

    # Tabla detalle por hoyo
    if ranked and hole_nums:
        st.subheader("📊 Detalle por hoyo")
        
        tabla_data = []
        for r in ranked:
            pid = r["pid"]
            row_data = {"Jugador": r["name"]}
            for h in hole_nums:
                v = scores_idx.get((pid, h), 0)
                row_data[f"H{h}"] = v if v > 0 else "—"
            row_data["Front"] = r["front"]
            row_data["Back"] = r["back"]
            row_data["Total"] = r["total"]
            tabla_data.append(row_data)

        df = pd.DataFrame(tabla_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# CAPTURAR SCORES
# ══════════════════════════════════════════════════════════════════════════════

def capture_ui():
    st.title("⛳ Capturar Scores — Grupo")

    # Restaurar desde URL
    if not st.session_state.get("group_auth"):
        code_from_url = st.query_params.get("code")
        if code_from_url and not st.session_state.get("_restoring_code"):
            st.session_state["_restoring_code"] = True
            result = get_group_by_code(code_from_url)
            if result:
                st.session_state["group_auth"] = result
                st.session_state["_restoring_code"] = False
                st.rerun()
            else:
                st.session_state["_restoring_code"] = False

    if st.session_state.get("group_auth"):
        group = st.session_state["group_auth"]["group"]
        torneo = st.session_state["group_auth"]["torneo"]
        st.success(f"✅ {group['name']} — {torneo['name']}")
        if st.button("🔄 Cambiar grupo"):
            st.session_state["group_auth"] = None
            st.query_params.clear()
            st.rerun()

        gid = group["id"]
        tid = torneo["id"]
        gps = get_group_players(gid)

        if not gps:
            st.warning("No hay jugadores en este grupo.")
            return

        scores_raw = get_scores(tid)
        scores_idx = {}
        for s in scores_raw:
            pid = s.get("player_id") or s.get("guest_id")
            scores_idx[(pid, s["hole_number"])] = s["strokes"]

        # Capturar por jugador
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
                    key=f"f_{gp['id']}_{h}", label_visibility="collapsed"
                ))

            # Back 9
            back_vals = []
            cols_b = st.columns(10)
            cols_b[0].markdown("Back")
            for i, h in enumerate(range(10, 19)):
                v = scores_idx.get((pid, h), 0)
                back_vals.append(cols_b[i+1].number_input(
                    "", min_value=0, max_value=20, value=int(v),
                    key=f"b_{gp['id']}_{h}", label_visibility="collapsed"
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
                st.success("Scores guardados!")

            st.markdown("---")
        return

    # Entrada de código
    st.markdown("**Ingresa el código de tu grupo:**")
    code = st.text_input("Código de grupo", max_chars=6, placeholder="123456")

    if st.button("Entrar", type="primary", use_container_width=True):
        if not code or len(code) != 6 or not code.isdigit():
            st.error("El código debe ser de 6 dígitos numéricos.")
            return
        result = get_group_by_code(code)
        if not result:
            st.error("Código no encontrado.")
            return
        st.session_state["group_auth"] = result
        st.query_params["code"] = code
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

def admin_panel():
    st.title("🔐 Admin — Medal Play")

    tab1, tab2, tab3, tab4 = st.tabs(["➕ Crear Torneo", "👥 Crear Grupo", "🔑 Ver Grupos", "🗑️ Borrar Torneo"])

    # ── TAB 1: Crear Torneo ────────────────────────────────────────────────────
    with tab1:
        st.header("Nuevo Torneo")
        courses = get_courses()
        if not courses:
            st.error("No hay campos en la BD.")
            return

        course_opts = {c["name"]: c for c in courses}
        default_idx = list(course_opts.keys()).index(DEFAULT_COURSE) if DEFAULT_COURSE in course_opts else 0
        sel_course = st.selectbox("Campo", list(course_opts.keys()), index=default_idx, key="t1_course")
        course = course_opts[sel_course]

        tees = get_tees(course["id"])
        if not tees:
            st.error("No hay tees para este campo.")
            return
        tee_opts = {t["color"]: t for t in tees}
        default_tee_idx = list(tee_opts.keys()).index(DEFAULT_TEE) if DEFAULT_TEE in tee_opts else 0
        sel_tee = st.selectbox("Tee", list(tee_opts.keys()), index=default_tee_idx, key="t1_tee",
                               format_func=lambda c: f"{c} — Rating {tee_opts[c]['rating']} / Slope {tee_opts[c]['slope']}")
        tee = tee_opts[sel_tee]

        fecha = st.date_input("Fecha", value=date.today(), key="t1_fecha")
        nombre = st.text_input("Nombre del torneo", value=f"Medal {date.today().strftime('%d-%b-%Y')}", key="t1_nombre")

        if st.button("Crear Torneo", type="primary", key="btn_crear_torneo"):
            if not nombre.strip():
                st.error("Ponle nombre al torneo.")
            else:
                torneo = create_tournament(nombre.strip(), str(fecha), tee["id"])
                if torneo:
                    st.success(f"Torneo '{nombre}' creado!")
                    st.session_state["admin_torneo_id"] = torneo["id"]
                else:
                    st.error("Error al crear el torneo.")

    # ── TAB 2: Crear Grupo ─────────────────────────────────────────────────────
    with tab2:
        st.header("Crear Grupo")
        torneos = get_tournaments()
        if not torneos:
            st.info("Primero crea un torneo.")
        else:
            t_opts = {f"{t['date']} — {t['name']}": t for t in torneos}
            saved_tid = st.session_state.get("admin_torneo_id")
            default_t_idx = 0
            if saved_tid:
                for i, t in enumerate(torneos):
                    if t["id"] == saved_tid:
                        default_t_idx = i
                        break
            sel_t_label = st.selectbox("Torneo", list(t_opts.keys()), index=default_t_idx, key="t2_torneo")
            torneo_sel = t_opts[sel_t_label]
            tid = torneo_sel["id"]
            st.session_state["admin_torneo_id"] = tid

            gname = st.text_input("Nombre del grupo", placeholder="Grupo 1", key="t2_gname")
            if st.button("Crear Grupo", type="primary", key="btn_crear_grupo"):
                if not gname.strip():
                    st.error("Ponle nombre al grupo.")
                else:
                    grp = create_group(tid, gname.strip())
                    st.success(f"Grupo '{gname}' creado — Código: `{grp['access_code']}`")
                    st.session_state["admin_grupo_id"] = grp["id"]

            # Agregar jugadores al grupo recien creado o a uno existente
            groups = get_groups(tid)
            if groups:
                st.markdown("---")
                st.subheader("Agregar jugadores a un grupo")
                grp_opts = {g["name"]: g for g in groups}
                saved_gid = st.session_state.get("admin_grupo_id")
                default_g_idx = 0
                if saved_gid:
                    for i, g in enumerate(groups):
                        if g["id"] == saved_gid:
                            default_g_idx = i
                            break
                sel_grp = st.selectbox("Grupo", list(grp_opts.keys()), index=default_g_idx, key="t2_grp")
                grp_sel = grp_opts[sel_grp]
                gid = grp_sel["id"]

                players_hdc = get_players()
                phdc_opts = {p["name"]: p for p in players_hdc}

                tipo = st.radio("Tipo de jugador", ["Registrado", "Invitado"], horizontal=True, key="t2_tipo")
                col_a, col_b = st.columns(2)
                if tipo == "Registrado":
                    with col_a:
                        sel_p = st.selectbox("Jugador", ["— Seleccionar —"] + list(phdc_opts.keys()), key="t2_jugador")
                    with col_b:
                        hcp_v = 0
                        if sel_p != "— Seleccionar —":
                            raw_hcp = phdc_opts[sel_p].get("current_handicap") or 0
                            hcp_v = round(float(raw_hcp))
                        hcp_input = st.number_input("Course HC", min_value=0, max_value=54, value=hcp_v, key="t2_hcp")
                    if st.button("Agregar jugador", type="primary", key="t2_btn_add"):
                        if sel_p != "— Seleccionar —":
                            pdata = phdc_opts[sel_p]
                            add_player_to_group(gid, pdata["name"], hcp_input, player_id=pdata["id"])
                            st.success(f"{pdata['name']} agregado!")
                            st.rerun()
                else:
                    with col_a:
                        guest_name = st.text_input("Nombre del invitado", key="t2_guestname")
                    with col_b:
                        hcp_input = st.number_input("Course HC", min_value=0, max_value=54, value=0, key="t2_ghcp")
                    if st.button("Agregar invitado", type="primary", key="t2_btn_guest"):
                        if guest_name.strip():
                            add_player_to_group(gid, guest_name.strip(), hcp_input)
                            st.success(f"{guest_name} agregado!")
                            st.rerun()

                # Lista actual del grupo
                gps = get_group_players(gid)
                if gps:
                    st.markdown(f"**Jugadores en {sel_grp}:**")
                    for gp in gps:
                        col1, col2 = st.columns([6, 1])
                        col1.write(f"• {gp['player_name']} (HC: {gp.get('course_handicap', '-')})")
                        if col2.button("✖", key=f"rm_{gp['id']}"):
                            remove_player_from_group(gp["id"])
                            st.rerun()

    # ── TAB 3: Ver Grupos ──────────────────────────────────────────────────────
    with tab3:
        st.header("Ver Grupos")
        torneos = get_tournaments()
        if not torneos:
            st.info("No hay torneos.")
        else:
            t_opts3 = {f"{t['date']} — {t['name']}": t for t in torneos}
            sel_t3 = st.selectbox("Torneo", list(t_opts3.keys()), index=None,
                                   placeholder="Selecciona un torneo...", key="t3_torneo")
            if sel_t3:
                tid3 = t_opts3[sel_t3]["id"]
                groups3 = get_groups(tid3)
                if not groups3:
                    st.info("Este torneo no tiene grupos.")
                else:
                    for grp in groups3:
                        with st.expander(f"👥 {grp['name']} — Código: `{grp['access_code']}`"):
                            gps = get_group_players(grp["id"])
                            if gps:
                                for gp in gps:
                                    st.write(f"• {gp['player_name']} (HC: {gp.get('course_handicap', '-')})")
                            else:
                                st.caption("Sin jugadores.")
                            if st.button(f"📝 Capturar scores", key=f"cap3_{grp['id']}", use_container_width=True):
                                st.session_state["group_auth"] = {"group": grp, "torneo": t_opts3[sel_t3]}
                                st.rerun()

    with tab4:
        st.header("Borrar Torneo")
        torneos = get_tournaments()
        if not torneos:
            st.info("No hay torneos.")
        else:
            t_opts4 = {f"{t['date']} — {t['name']}": t for t in torneos}
            sel_t4 = st.selectbox("Torneo", list(t_opts4.keys()), index=None, placeholder="Selecciona...", key="t4_torneo")
            if sel_t4:
                t4 = t_opts4[sel_t4]
                st.warning(f"Se borrarán el torneo, todos sus grupos y scores. ¿Confirmas?")
                if st.button("🗑️ Borrar este torneo", type="primary", key="t4_btn_borrar"):
                    delete_tournament(t4["id"])
                    st.success("Torneo borrado.")
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.sidebar.title("⛳ Medal Play")

    default_idx = 0
    if st.session_state.get("group_auth"):
        default_idx = 1
    elif st.session_state.get("admin_logged_in"):
        default_idx = 2

    vista = st.sidebar.radio("Vista", ["🏆 Leaderboard", "🎯 Capturar", "🔐 Admin"], index=default_idx)

    if vista == "🔐 Admin":
        if not st.session_state.get("admin_logged_in"):
            admin_login()
        else:
            if st.sidebar.button("Cerrar sesión"):
                st.session_state["admin_logged_in"] = False
                st.session_state["access_token"] = None
                st.session_state["refresh_token"] = None
                st.query_params.pop("_rt", None)
                st.rerun()
            admin_panel()
    elif vista == "🎯 Capturar":
        capture_ui()
    else:
        leaderboard_ui()

if __name__ == "__main__":
    main()
