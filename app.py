import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State, ALL
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import json
import re
import copy
import time
import sqlite3

# --- CONFIGURATION & CONSTANTES ---

DB_NAME = 'match_stats.db'

# URL mise à jour avec l'image du demi-terrain
URL_IMAGE_TERRAIN = "https://raw.githubusercontent.com/takerusumida-lgtm/agent-stats-volley-veec/c8e81f5fd7ec811428e8bfbc5b5d880614f5fc40/Volleyball_Half_Court.png"

VEEC_ZONES_COORDS = {
    1: {"x": 75, "y": 45, "name": "P1 (Arrière Droit)"}, 6: {"x": 50, "y": 45, "name": "P6 (Arrière Centre)"},
    5: {"x": 25, "y": 45, "name": "P5 (Arrière Gauche)"}, 2: {"x": 75, "y": 78, "name": "P2 (Avant Droit)"},
    3: {"x": 50, "y": 78, "name": "P3 (Avant Centre)"}, 4: {"x": 25, "y": 78, "name": "P4 (Avant Gauche)"},
}

LISTE_JOUEURS_PREDEFINIE = [
    {"numero": 1, "nom": "N. Passeur"}, {"numero": 4, "nom": "D. Pointu"},
    {"numero": 6, "nom": "M. Central"}, {"numero": 8, "nom": "A. Libero"},
    {"numero": 10, "nom": "C. Réception"}, {"numero": 12, "nom": "E. Serviteur"},
    {"numero": 2, "nom": "G. Passeur 2"}, {"numero": 5, "nom": "H. Pointu 2"},
    {"numero": 7, "nom": "J. Central 2"}, {"numero": 9, "nom": "B. Libero 2"},
    {"numero": 11, "nom": "F. Réception 2"}, {"numero": 13, "nom": "K. Serviteur 2"},
]

VEEC_COLOR = "#007bff"
ADVERSE_COLOR = "#dc3545"

ACTION_CATEGORIES = [
    ("SERVICE", "SVC", [
        ("🎯 Ace (P)", "ACE", '#28a745'),      
        ("🔄 Service OK (0)", "OK", '#ffc107'),  
        ("💥 Erreur (Adv P)", "ERR", '#dc3545') 
    ]),
    ("RÉCEPTION", "REC", [
        ("✅ Parfaite (+)", "PERF", '#28a745'), 
        ("👐 Moyenne (0)", "OK", '#ffc107'),   
        ("💔 Manquée (Adv P)", "ERR", '#dc3545') 
    ]),
    ("PASSE", "PAS", [
        ("⭐ Parfaite (+)", "PERF", '#17a2b8'), 
        ("👐 Moyenne (0)", "OK", '#ffc107'),   
        ("❌ Mauvaise Passe (Adv P)", "ERR", '#dc3545') 
    ]),
    ("ATTAQUE", "ATK", [
        ("💥 Point (P)", "POINT", '#28a745'),  
        ("👐 Contre (0)", "CONTRE", '#ffc107'), 
        ("❌ Faute (Adv P)", "ERR", '#dc3545')  
    ]),
    ("BLOC", "BLK", [
        ("🛡️ Point (P)", "POINT", '#28a745'),   
        ("🚫 Touché (0)", "TOUCH", '#17a2b8'),   
        ("⛔ Faute (Adv P)", "ERR", '#dc3545')    
    ]),
]

# RÈGLES DU VOLLEY-BALL
POINTS_POUR_GAGNER = 25
POINTS_POUR_GAGNER_SET_DECISIF = 15 # Non implémenté ici pour la simplification, on utilise 25
MAX_SETS = 5 # Match au meilleur des 5 sets (3 sets gagnants)

# --- UTILITIES ---

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Création de la table 'actions'
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY,
            match_id TEXT NOT NULL,
            set_num INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            score_at_action TEXT NOT NULL,
            position TEXT NOT NULL,
            joueur_nom TEXT NOT NULL,
            action_code TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
# Appeler cette fonction une fois au début de l'exécution
init_db()

def insert_stat(match_id, set_num, timestamp, score_at_action, position, joueur_nom, action_code):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO actions (match_id, set_num, timestamp, score_at_action, position, joueur_nom, action_code) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (match_id, set_num, timestamp, score_at_action, position, joueur_nom, action_code))
    
    conn.commit()
    conn.close()

# --- FONCTION D'AIDE SQLite ---

def delete_last_stat_and_get_data(match_id):
    """
    Supprime la dernière ligne enregistrée pour le match_id donné et retourne
    l'action code et le set de l'entrée supprimée pour la correction du score Dash.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Sélectionner la dernière ligne (ID le plus élevé) pour le match en cours
    cursor.execute("""
        SELECT id, action_code, set_num, score_at_action
        FROM actions 
        WHERE match_id = ? 
        ORDER BY id DESC 
        LIMIT 1
    """, (match_id,))
    last_row = cursor.fetchone()

    if last_row:
        last_id, action_code, set_num, score_at_action = last_row
        
        # 2. Supprimer la ligne
        cursor.execute("DELETE FROM actions WHERE id = ?", (last_id,))
        conn.commit()
        conn.close()
        
        # 3. Retourner les données importantes pour la correction du score
        return {'action': action_code, 'set': set_num, 'score_avant_action': score_at_action}
    
    conn.close()
    return None

def create_historique_table(historique_stats):
    if not historique_stats:
        return html.Div("Aucune stat enregistrée.", style={'padding': '10px', 'color': '#666'})
    df = pd.DataFrame(historique_stats)
    # Mise à jour des colonnes pour inclure 'set' et 'score'
    cols = ['timestamp', 'set', 'score', 'pos', 'joueur', 'action'] 
    df = df[[c for c in cols if c in df.columns]]
    return dash_table.DataTable(
        columns=[{"name": i.capitalize(), "id": i} for i in df.columns],
        data=df.head(50).to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#f8f9fa', 'fontWeight': 'bold'},
        style_cell={'textAlign': 'left'}
    )

def create_simple_court_figure():
    """Crée le terrain avec 6 zones cliquables statiques."""
    fig = go.Figure()
    fig.add_layout_image(
        dict(source=URL_IMAGE_TERRAIN, xref="x", yref="y", x=0, y=100, sizex=100, sizey=100,
             sizing="stretch", opacity=1.0, layer="below"))

    x_coords = [VEEC_ZONES_COORDS[p]["x"] for p in VEEC_ZONES_COORDS]
    y_coords = [VEEC_ZONES_COORDS[p]["y"] for p in VEEC_ZONES_COORDS]
    text_labels = [f"P{p}" for p in VEEC_ZONES_COORDS]
    custom_data = [p for p in VEEC_ZONES_COORDS]

    fig.add_trace(go.Scatter(
        x=x_coords, y=y_coords, mode="markers+text",
        marker=dict(size=60, color=VEEC_COLOR, opacity=0.7, line=dict(width=2, color="white")),
        text=text_labels, textfont=dict(color="white", size=20),
        customdata=custom_data, hoverinfo='text',
        hovertext=[VEEC_ZONES_COORDS[p]["name"] for p in VEEC_ZONES_COORDS]
    ))

    fig.update_layout(
        xaxis=dict(range=[0, 100], visible=False, fixedrange=True),
        yaxis=dict(range=[0, 100], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1.0),
        margin=dict(l=0, r=0, t=0, b=0), showlegend=False, clickmode='event',
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- LOGIQUE DU JEU VOLLEY-BALL ---
def check_set_and_match_end(new_state):
    """Vérifie la fin du set (25 points, +2 écart) et la fin du match."""
    score_veec = new_state['score_veec']
    score_adverse = new_state['score_adverse']
    
    # Définir le score minimum requis
    # NOTE: Simplifié pour utiliser 25 points pour tous les sets.
    # En réalité, le 5e set est à 15 points.
    target_score = POINTS_POUR_GAGNER

    set_ended = False
    set_winner = None

    # 1. Vérification de la fin de set
    if score_veec >= target_score and (score_veec - score_adverse) >= 2:
        set_ended = True
        set_winner = 'VEEC'
    elif score_adverse >= target_score and (score_adverse - score_veec) >= 2:
        set_ended = True
        set_winner = 'ADVERSE'

    if set_ended:
        # 2. Mise à jour des sets gagnés
        if set_winner == 'VEEC':
            new_state['sets_veec'] += 1
        else:
            new_state['sets_adverse'] += 1
            
        # 3. Vérification de la fin de match (3 sets gagnants)
        if new_state['sets_veec'] >= 3 or new_state['sets_adverse'] >= 3:
            # Le match est terminé
            # On pourrait ajouter une variable 'match_over' pour bloquer l'interface
            log_entry = {
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'set': new_state['current_set'],
                'score': f"{score_veec}-{score_adverse}",
                'pos': 'FIN',
                'joueur': set_winner,
                'action': 'FIN_MATCH'
            }
            new_state['historique_stats'].insert(0, log_entry)
            
            # Optionnel: Réinitialiser les scores, mais garder les sets finaux
            # new_state['score_veec'] = 0
            # new_state['score_adverse'] = 0
            # new_state['current_set'] = MAX_SETS # ou une valeur spéciale

        else:
            # Le set est terminé, passage au set suivant
            new_state['current_set'] += 1
            new_state['score_veec'] = 0
            new_state['score_adverse'] = 0
            
            # Enregistrement d'une ligne de fin de set pour le log
            log_entry = {
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'set': new_state['current_set'] - 1, # Set qui vient de se terminer
                'score': f"{score_veec}-{score_adverse}",
                'pos': 'FIN',
                'joueur': set_winner,
                'action': 'FIN_SET'
            }
            new_state['historique_stats'].insert(0, log_entry)

    return new_state


# --- INITIALISATION ---

initial_state = {
    'match_id': f"Match_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    'score_veec': 0, 'score_adverse': 0,
    'sets_veec': 0, 'sets_adverse': 0,
    'current_set': 1,
    'historique_stats': [],
    'temp_selected_pos': None, 
    'temp_selected_player': None, 
    'click_count': 0 
}

# --- LAYOUT ---

app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.layout = html.Div([
    dcc.Store(id='match-state', data=initial_state),
    dcc.Store(id='click-reset-trigger', data=0), 
    
    html.Div([
        html.Div("VEEC", style={'fontSize': '2em', 'fontWeight': 'bold', 'color': VEEC_COLOR}),
        html.Div([
            # Affichage du score par set
            html.Span(f"Sets: {initial_state['sets_veec']}", id='sets-veec-display', style={'fontSize': '1.5em', 'marginRight': '10px', 'color': VEEC_COLOR}),
            
            html.Span(id='score-veec-display', children=str(initial_state['score_veec']), style={'fontSize': '3em', 'marginRight': '20px'}),
            html.Span("-", style={'fontSize': '3em'}),
            html.Span(id='score-adverse-display', children=str(initial_state['score_adverse']), style={'fontSize': '3em', 'marginLeft': '20px'}),
            
            # Affichage du score par set
            html.Span(f"Sets: {initial_state['sets_adverse']}", id='sets-adverse-display', style={'fontSize': '1.5em', 'marginLeft': '10px', 'color': ADVERSE_COLOR}),
        ], style={'display': 'flex', 'alignItems': 'center'}),
        html.Div("ADVERSAIRE", style={'fontSize': '2em', 'fontWeight': 'bold', 'color': ADVERSE_COLOR}),
    ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'padding': '20px', 'borderBottom': '1px solid #ccc', 'backgroundColor': 'white'}),


    html.Div([
        html.H4(f"Set en cours : {initial_state['current_set']}", id='current-set-display', style={'textAlign': 'center'}),
        html.Div([
            html.Div(f"ID du Match : {initial_state['match_id']}", id='match-id-display', 
                     style={'fontSize': '0.9em', 'color': '#6c757d', 'marginRight': '20px'}),

            # NOUVEAU: Bouton pour annuler la dernière action
            html.Button("↩️ Annuler la dernière action", id='btn-undo-last', n_clicks=0, 
                        style={'padding': '5px 15px', 'backgroundColor': '#ff6347', 'color': 'white', 
                               'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'marginRight': '20px'}),

            html.Button("🔄 Nouveau Match", id='btn-new-match', n_clicks=0, 
                        style={'padding': '5px 15px', 'backgroundColor': '#ffc107', 'color': 'black', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer'})
        ], style={'display': 'flex', 'justifyContent': 'center', 'alignItems': 'center', 'marginBottom': '20px'}) # NOUVEAU CONTENEUR FLEX
    ], style={'textAlign': 'center', 'marginTop': '10px'}),

    dcc.Graph(
        id='terrain-graph-simple',
        figure=create_simple_court_figure(),
        config={'displayModeBar': False, 'scrollZoom': False},
        style={'height': '60vh'}
    ),

    html.Div(id='input-modal-container'),

    html.Hr(),
    html.H3("Historique", style={'textAlign': 'center'}),
    html.Div(id='historique-display', style={'padding': '20px'})
])

# --- CALLBACKS ---

# 1. Gestion du Workflow de Saisie (Terrain -> Joueur -> Action UI)
@app.callback(
    [Output('input-modal-container', 'children'),
     Output('match-state', 'data', allow_duplicate=True)],
    [
        Input('terrain-graph-simple', 'clickData'),
        Input({'type': 'select-player-btn', 'index': ALL}, 'n_clicks'),
        Input({'type': 'modal-control', 'action': ALL}, 'n_clicks')
    ],
    [State('match-state', 'data')],
    prevent_initial_call=True
)
def handle_stat_workflow(clickData, n_player_btn, n_control_btn, current_state):
    ctx = dash.callback_context
    if not ctx.triggered: return dash.no_update, dash.no_update

    triggered_id = ctx.triggered[0]['prop_id']
    new_state = copy.deepcopy(current_state)

    # Clause de garde pour bloquer l'ajout de stat si le match est terminé
    if new_state.get('sets_veec', 0) >= 3 or new_state.get('sets_adverse', 0) >= 3:
        return None, dash.no_update # Ferme la modale si elle est ouverte et bloque l'action

    # --- Déclencheur : Annulation ---
    if 'modal-control' in triggered_id:
        try:
            triggered_dict = json.loads(triggered_id.split('.')[0])
            if triggered_dict.get('action') == 'cancel':
                new_state['temp_selected_pos'] = None
                new_state['temp_selected_player'] = None
                return None, new_state
        except json.JSONDecodeError:
            pass

    # --- Phase 1 : Clic Terrain (Sélection Joueur) ---
    if 'terrain-graph-simple' in triggered_id and clickData:
        pos = clickData['points'][0]['customdata']
        new_state['temp_selected_pos'] = pos
        new_state['temp_selected_player'] = None
        
        player_buttons = []
        for p in LISTE_JOUEURS_PREDEFINIE:
            player_buttons.append(html.Button(
                f"N°{p['numero']} - {p['nom']}", 
                id={'type': 'select-player-btn', 'index': p['numero']},
                n_clicks=0,
                style={'margin': '5px', 'padding': '10px 15px', 'fontSize': '1.0em', 'borderRadius': '5px', 'border': f'1px solid {VEEC_COLOR}', 'backgroundColor': '#fff', 'cursor': 'pointer'}
            ))
        
        modal_content = html.Div([
            html.Div([
                html.H3(f"P{pos} : Quel joueur ?", style={'textAlign': 'center', 'marginBottom': '20px'}),
                html.Div(player_buttons, style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center', 'maxHeight': '60vh', 'overflowY': 'auto'}),
                html.Button("Annuler", id={'type': 'modal-control', 'action': 'cancel'}, style={'marginTop': '20px', 'width': '100%', 'padding': '10px', 'backgroundColor': '#ccc', 'color': 'black'})
            ], style={'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '15px', 'width': '90%', 'maxWidth': '600px', 'boxShadow': '0 5px 15px rgba(0,0,0,0.3)'})
        ], style={'position': 'fixed', 'top': 0, 'left': 0, 'width': '100%', 'height': '100%', 'backgroundColor': 'rgba(0,0,0,0.6)', 'display': 'flex', 'justifyContent': 'center', 'alignItems': 'center', 'zIndex': 2000})
        
        return modal_content, new_state

    # --- Phase 2 : Clic Joueur (Sélection Action UI) ---
    if 'select-player-btn' in triggered_id:
        # ... (Logique de création de la modale inchangée)
        btn_id_dict = json.loads(triggered_id.split('.')[0])
        player_num = btn_id_dict['index']
        
        new_state['temp_selected_player'] = player_num 
        
        pos = new_state['temp_selected_pos']
        player_name = next((p['nom'] for p in LISTE_JOUEURS_PREDEFINIE if p['numero'] == player_num), f"N°{player_num}")
        
        # --- GENERATION DES BOUTONS EN COLONNES ---
        cols = []
        for title, code_base, buttons in ACTION_CATEGORIES:
            button_elements = []
            for label, code_result, bg_color in buttons:
                action_value = f"{code_base}_{code_result}"
                btn_id = {'type': 'select-action-btn', 'value': action_value}
                button_elements.append(
                    html.Button(label, id=btn_id, n_clicks=0,
                        style={'width': '100%', 'marginBottom': '8px', 'backgroundColor': bg_color, 'color': 'white', 
                               'border': 'none', 'padding': '12px 0', 'borderRadius': '5px', 'fontSize': '1.1em', 
                               'cursor': 'pointer', 'fontWeight': 'bold'}
                    ))
            
            cols.append(
                html.Div([
                    html.H4(title, style={'textAlign': 'center', 'fontSize': '1.3em', 'marginBottom': '15px', 'color': '#333'}),
                    *button_elements
                ], style={'width': '19%', 'display': 'inline-block', 'padding': '0 0.5%', 'verticalAlign': 'top', 'boxSizing': 'border-box'}))

        content_style = {
            'backgroundColor': 'white', 'padding': '30px', 'borderRadius': '15px', 'width': '95%', 
            'maxWidth': '900px', 'boxShadow': '0 8px 16px rgba(0,0,0,0.4)', 'maxHeight': '90vh', 
            'overflowY': 'auto', 'position': 'relative', 'zIndex': 1002 
        }
        modal_style = {
            'position': 'fixed', 'top': 0, 'left': 0, 'width': '100%', 'height': '100%',
            'backgroundColor': 'rgba(0,0,0,0.7)', 'display': 'flex', 'justifyContent': 'center', 
            'alignItems': 'center', 'zIndex': 2000 
        }

        modal_content_inner = html.Div(
            children=[
                html.Div([
                    html.H3(f"Saisie Stat : N°{player_num} ({player_name}) - P{pos}", 
                            style={'textAlign': 'center', 'color': '#333'}),
                    
                    html.Button("✕ Annuler", id={'type': 'modal-control', 'action': 'cancel'}, n_clicks=0, 
                        style={'position': 'absolute', 'top': '10px', 'right': '10px', 'backgroundColor': 'transparent', 
                               'border': 'none', 'fontSize': '1.2em', 'cursor': 'pointer', 'color': '#333', 'padding': '10px'})
                ], style={'position': 'relative', 'marginBottom': '20px'}),
                
                html.Div(cols, style={'display': 'flex', 'justifyContent': 'space-around', 'flexWrap': 'wrap'})
            ], style=content_style
        )
        
        modal_content = html.Div(children=modal_content_inner, style=modal_style)
        
        return modal_content, new_state

    return dash.no_update, dash.no_update

# 2. Validation et Traitement Final de la Statistique (Mis à jour pour la gestion du score et des sets)
@app.callback(
    [Output('match-state', 'data', allow_duplicate=True),
     Output('input-modal-container', 'children', allow_duplicate=True),
     Output('historique-display', 'children'),
     Output('score-veec-display', 'children'),
     Output('score-adverse-display', 'children'),
     Output('sets-veec-display', 'children'), # Affichage des sets
     Output('sets-adverse-display', 'children'), # Affichage des sets
     Output('current-set-display', 'children'), # Affichage du set actuel
     Output('click-reset-trigger', 'data')], 
    [Input({'type': 'select-action-btn', 'value': ALL}, 'n_clicks')],
    [State('match-state', 'data')],
    prevent_initial_call=True
)
def process_stat_entry(action_clicks, current_state):
    ctx = dash.callback_context
    if not ctx.triggered: return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    triggered_input = ctx.triggered[0]
    triggered_id = triggered_input['prop_id']
    action_clicks_value = triggered_input['value']

    if 'select-action-btn' not in triggered_id:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    if action_clicks_value is None or action_clicks_value == 0:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    new_state = copy.deepcopy(current_state)
    
    pos = new_state['temp_selected_pos']
    player_val = new_state['temp_selected_player']
    
    if pos is None or player_val is None:
        return dash.no_update, None, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    triggered_id_dict = json.loads(triggered_id.split('.')[0])
    action_val = triggered_id_dict['value']
    
    player_name = next((p['nom'] for p in LISTE_JOUEURS_PREDEFINIE if p['numero'] == player_val), f"N°{player_val}")
    
    # --- 1. Mise à Jour du Score ---
    score_avant_action = f"{new_state['score_veec']}-{new_state['score_adverse']}"
    if '_ACE' in action_val or '_POINT' in action_val:
        new_state['score_veec'] += 1
    elif '_ERR' in action_val:
        new_state['score_adverse'] += 1
        
    # --- 2. Enregistrer la stat enrichie ---
    log_entry = {
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'set': new_state['current_set'], # Numéro du set en cours
        'score': score_avant_action, # Score au moment du clic (avant l'incrémentation finale)
        'pos': f"P{pos}",
        'joueur': player_name,
        'action': action_val
    }
    new_state['historique_stats'].insert(0, log_entry)
    
    # --- 3. Vérification de la Fin de Set / Match ---
    new_state = check_set_and_match_end(new_state)

    if 'FIN_SET' not in action_val and 'FIN_MATCH' not in action_val:
        # On n'insère dans la DB que si la stat est complète (pas les lignes de 'FIN_SET' ou 'FIN_MATCH' déjà ajoutées par check_set_and_match_end)
        
        # NOTE : Utiliser les variables créées localement dans le callback
        current_match_id = new_state['match_id']
        
        insert_stat(
            match_id=current_match_id,
            set_num=new_state['current_set'],
            timestamp=datetime.now().strftime("%H:%M:%S"),
            score_at_action=score_avant_action,
            position=f"P{pos}",
            joueur_nom=player_name,
            action_code=action_val
        )
    
    # --- 4. Réinitialisation de l'état temporaire et mise à jour de l'affichage ---
    new_state['temp_selected_pos'] = None
    new_state['temp_selected_player'] = None
    new_state['click_count'] = new_state.get('click_count', 0) + 1
            
    histo_table = create_historique_table(new_state['historique_stats'])
    
    # Mise à jour des outputs d'affichage
    score_veec_out = str(new_state['score_veec'])
    score_adverse_out = str(new_state['score_adverse'])
    sets_veec_out = f"Sets: {new_state['sets_veec']}"
    sets_adverse_out = f"Sets: {new_state['sets_adverse']}"
    current_set_out = f"Set en cours : {new_state['current_set']}"
    
    # Si le match est fini, on l'indique dans l'affichage du set
    if new_state.get('sets_veec', 0) >= 3 or new_state.get('sets_adverse', 0) >= 3:
        current_set_out = "MATCH TERMINÉ !"

    return (
        new_state, 
        None, 
        histo_table, 
        score_veec_out, 
        score_adverse_out, 
        sets_veec_out, 
        sets_adverse_out,
        current_set_out,
        new_state['click_count']
    )

# 3. Callback de Réinitialisation 
@app.callback(
    Output('terrain-graph-simple', 'clickData'),
    Input('click-reset-trigger', 'data'),
    prevent_initial_call=True
)
def reset_click_data(trigger_data):
    """Réinitialise clickData après qu'une statistique a été enregistrée."""
    if trigger_data > 0:
        return None
    return dash.no_update

def fetch_all_stats(match_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row # Permet d'accéder aux colonnes par leur nom
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM actions WHERE match_id = ? ORDER BY id DESC", (match_id,))
    rows = cursor.fetchall()
    
    conn.close()
    
    # Convertir en liste de dictionnaires
    return [dict(row) for row in rows]


# 5. Callback de Démarrage d'un Nouveau Match
@app.callback(
    [Output('match-state', 'data', allow_duplicate=True),
     Output('score-veec-display', 'children', allow_duplicate=True),
     Output('score-adverse-display', 'children', allow_duplicate=True),
     Output('sets-veec-display', 'children', allow_duplicate=True),
     Output('sets-adverse-display', 'children', allow_duplicate=True),
     Output('current-set-display', 'children', allow_duplicate=True),
     Output('match-id-display', 'children', allow_duplicate=True),
     Output('historique-display', 'children', allow_duplicate=True),
     Output('export-status-output', 'children', allow_duplicate=True)], # Clear statut export
    [Input('btn-new-match', 'n_clicks')],
    prevent_initial_call=True
)
def start_new_match(n_clicks):
    if n_clicks is None or n_clicks == 0:
        return dash.no_update
        
    # Création d'un NOUVEL état initial
    new_match_id = f"Match_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    new_initial_state = {
        'match_id': new_match_id, 
        'score_veec': 0, 
        'score_adverse': 0,
        'sets_veec': 0, 
        'sets_adverse': 0,
        'current_set': 1,
        'historique_stats': [],
        'temp_selected_pos': None, 
        'temp_selected_player': None, 
        'click_count': 0 
    }
    
    # Mise à jour des outputs d'affichage
    sets_veec_out = f"Sets: {new_initial_state['sets_veec']}"
    sets_adverse_out = f"Sets: {new_initial_state['sets_adverse']}"
    current_set_out = f"Set en cours : {new_initial_state['current_set']}"
    match_id_out = f"ID du Match : {new_initial_state['match_id']}"
    
    # Réinitialisation de l'historique affiché
    histo_table = create_historique_table([]) 
    
    return (
        new_initial_state, 
        str(new_initial_state['score_veec']), 
        str(new_initial_state['score_adverse']), 
        sets_veec_out, 
        sets_adverse_out,
        current_set_out,
        match_id_out,
        histo_table,
        "" # Efface le message de statut d'export
    )


# 6. Callback d'Annulation de la Dernière Action
@app.callback(
    [Output('match-state', 'data', allow_duplicate=True),
     Output('historique-display', 'children', allow_duplicate=True),
     Output('score-veec-display', 'children', allow_duplicate=True),
     Output('score-adverse-display', 'children', allow_duplicate=True),
     Output('sets-veec-display', 'children', allow_duplicate=True),
     Output('sets-adverse-display', 'children', allow_duplicate=True),
     Output('current-set-display', 'children', allow_duplicate=True)],
    [Input('btn-undo-last', 'n_clicks')],
    [State('match-state', 'data')],
    prevent_initial_call=True
)
def handle_undo(n_clicks, current_state):
    if n_clicks is None or n_clicks == 0:
        return dash.no_update
    
    new_state = copy.deepcopy(current_state)
    match_id = new_state.get('match_id')

    if not new_state['historique_stats']:
        # Rien à annuler dans l'état Dash
        return dash.no_update
        
    # --- 1. Suppression de la dernière entrée SQLite ---
    deleted_data = delete_last_stat_and_get_data(match_id)
    
    # --- 2. Suppression de la dernière entrée dans l'état Dash ---
    removed_entry = new_state['historique_stats'].pop(0) # Le plus récent est à l'index 0
    
    if not deleted_data:
        # Aucune donnée supprimée dans la DB (ça ne devrait pas arriver si l'historique Dash n'est pas vide)
        return dash.no_update 
    
    action_code = removed_entry['action']

    # --- 3. Correction de la Logique de Score et de Set ---
    
    # CAS A : Annuler la FIN de MATCH
    if action_code == 'FIN_MATCH':
        # On supprime le flag de fin de match, mais l'action précédente est FIN_SET, qui sera traitée après
        
        # On continue la boucle pour traiter l'action FIN_SET qui est maintenant la dernière entrée de l'historique
        if new_state['historique_stats'][0]['action'] == 'FIN_SET':
            removed_entry = new_state['historique_stats'].pop(0)
            action_code = removed_entry['action']
            delete_last_stat_and_get_data(match_id) # Supprime le FIN_SET de la DB

    # CAS B : Annuler la FIN de SET
    if action_code == 'FIN_SET':
        # La ligne FIN_SET contient le score final du set (ex: 25-23). 
        # L'action précédente dans l'historique est le point gagnant du set.
        
        # Récupérer le score du set précédent (avant le point gagnant) à partir de l'entrée précédente
        score_set_precedent_str = removed_entry['score'] # score au moment du point gagnant
        score_veec_final, score_adverse_final = map(int, score_set_precedent_str.split('-'))
        
        # On revient au set précédent
        new_state['current_set'] -= 1
        
        # On décrémente le compteur de sets gagnés
        if removed_entry['joueur'] == 'VEEC':
            new_state['sets_veec'] -= 1
        else:
            new_state['sets_adverse'] -= 1
            
        # On charge le score qui était en cours juste avant la fin du set
        new_state['score_veec'] = score_veec_final
        new_state['score_adverse'] = score_adverse_final
        
        # L'action du point gagnant doit maintenant être annulée par la logique suivante (CAS C)
        
    # CAS C : Annuler un point/erreur régulier
    
    # Si on n'est pas en train d'annuler une FIN_SET/MATCH, on annule un point/erreur simple
    if action_code != 'FIN_SET' and action_code != 'FIN_MATCH':
        if '_ACE' in action_code or '_POINT' in action_code:
            new_state['score_veec'] -= 1
        elif '_ERR' in action_code:
            new_state['score_adverse'] -= 1
            
        # Protection contre un score négatif (si on annule le score 0-0)
        new_state['score_veec'] = max(0, new_state['score_veec'])
        new_state['score_adverse'] = max(0, new_state['score_adverse'])


    # --- 4. Mise à jour de l'affichage (similaire à process_stat_entry) ---
    
    histo_table = create_historique_table(new_state['historique_stats'])
    
    score_veec_out = str(new_state['score_veec'])
    score_adverse_out = str(new_state['score_adverse'])
    sets_veec_out = f"Sets: {new_state['sets_veec']}"
    sets_adverse_out = f"Sets: {new_state['sets_adverse']}"
    
    if new_state.get('sets_veec', 0) >= 3 or new_state.get('sets_adverse', 0) >= 3:
        current_set_out = "MATCH TERMINÉ !"
    else:
        current_set_out = f"Set en cours : {new_state['current_set']}"

    return (
        new_state, 
        histo_table, 
        score_veec_out, 
        score_adverse_out, 
        sets_veec_out, 
        sets_adverse_out,
        current_set_out
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8051)
