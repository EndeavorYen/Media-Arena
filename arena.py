import gradio as gr
import os
import random
from pathlib import Path
import pandas as pd
from collections import defaultdict

# --- JavaScript for custom video controls ---
js_script = """
async function() {
    await new Promise(r => setTimeout(r, 100));
    const left_video_container = document.querySelector("#left-media-display");
    const right_video_container = document.querySelector("#right-media-display");
    if (!left_video_container || !right_video_container) return;
    const left_video = left_video_container.querySelector("video");
    const right_video = right_video_container.querySelector("video");
    if (!left_video || !right_video) return;
    const controls_container = document.querySelector("#custom-video-controls");
    if (!controls_container) return; 
    const play_pause_btn = document.getElementById("play-pause-btn");
    const slider = document.getElementById("timeline-slider");
    play_pause_btn.textContent = "▶️ 同步播放";
    slider.value = 0;
    play_pause_btn.onclick = () => {
        if (left_video.paused) { left_video.play(); right_video.play(); } 
        else { left_video.pause(); right_video.pause(); }
    };
    let is_seeking = false;
    const onTimeUpdate = () => { if (!is_seeking && !left_video.paused) slider.value = left_video.currentTime; };
    const onLoadedMetadata = () => { slider.max = left_video.duration; };
    left_video.addEventListener('loadedmetadata', onLoadedMetadata);
    left_video.addEventListener('timeupdate', onTimeUpdate);
    slider.oninput = () => { is_seeking = true; const time = slider.value; left_video.currentTime = time; right_video.currentTime = time; };
    slider.onchange = () => { is_seeking = false; };
    const updateButtonText = () => { play_pause_btn.textContent = left_video.paused ? "▶️ 同步播放" : "⏸️ 同步暫停"; };
    left_video.addEventListener('play', updateButtonText);
    left_video.addEventListener('pause', updateButtonText);
}
"""

# --- ELO Rating Calculation ---
def calculate_elo(player_a_rating, player_b_rating, result):
    k_factor = 32
    expected_a = 1 / (1 + 10**((player_b_rating - player_a_rating) / 400))
    expected_b = 1 - expected_a 
    new_rating_a = player_a_rating + k_factor * (result - expected_a)
    new_rating_b = player_b_rating + k_factor * ((1 - result) - expected_b)
    return round(new_rating_a), round(new_rating_b)

# --- Swiss Pairing Algorithm ---
def create_swiss_pairings(state):
    """Creates pairings for the next round based on Swiss system rules."""
    players_by_score = defaultdict(list)
    for p_id, data in state["players"].items():
        players_by_score[data.get("score", 0)].append(p_id)
    
    new_matchups = []
    sorted_scores = sorted(players_by_score.keys(), reverse=True)
    
    unpaired_players = []
    for score in sorted_scores:
        bracket = players_by_score[score]
        random.shuffle(bracket)
        bracket = unpaired_players + bracket
        unpaired_players = []
        
        if len(bracket) % 2 != 0:
            unpaired_players.append(bracket.pop(-1))

        for i in range(0, len(bracket), 2):
            p1, p2 = bracket[i], bracket[i+1]
            if not has_played(p1, p2, state):
                new_matchups.append((p1, p2))
            else:
                 unpaired_players.extend([p1, p2])

    return new_matchups

def has_played(p1, p2, state):
    """Check if two players have already played."""
    return (p1, p2) in state["match_history"] or (p2, p1) in state["match_history"]

# --- Helper Functions ---
def is_media_file(filename): return any(str(filename).lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS)
def is_video_file(filename): return any(str(filename).lower().endswith(ext) for ext in ['.mp4', '.mov', '.avi', '.mkv'])

# --- Core Logic ---
def start_tournament(files_list, tournament_type, total_rounds):
    if not files_list:
        gr.Warning("請選擇或拖放一個資料夾！")
        return (None,) + (gr.update(),) * 10

    files = [f.name for f in files_list if is_media_file(f.name)]
    if len(files) < 2:
        gr.Warning("資料夾中需要至少 2 個支援的媒體檔案才能開始比賽！")
        return (None, gr.update(value="錯誤：有效的媒體檔案數量不足。")) + (gr.update(visible=False),) * 9

    state = {"mode": tournament_type, "original_filenames": {path: Path(path).name for path in files}, "players": {}, "matchups": []}

    if tournament_type == "單淘汰賽":
        random.shuffle(files)
        state.update({"players": {f: {"status": "active"} for f in files}, "matchups": list(zip(files[::2], files[1::2])), "current_match_index": 0, "round": 1})
        if len(files) % 2 != 0: state["players"][files[-1]]["status"] = "winner"
    elif tournament_type == "循環評分賽 (ELO)":
        state.update({
            "players": {f: {"elo": 1500, "score": 0, "matches": 0} for f in files},
            "total_rounds": int(total_rounds), "current_round": 1,
            "match_history": set(), "matchups_this_round": [], "current_match_index": 0
        })
        state["matchups_this_round"] = create_swiss_pairings(state)
    
    return display_match(state)

def display_match(state):
    if not isinstance(state, dict): return (None, gr.update(value="發生內部錯誤，請重試。")) + (gr.update(),) * 9

    mode = state["mode"]
    updates = [gr.update()] * 11
    for i in range(2, 11): updates[i] = gr.update(visible=False)
    
    def set_updates(info, l_vis=False, t_vis=False, r_vis=False, c_vis=False):
        updates[1] = gr.update(value=info)
        updates[4], updates[5], updates[6] = gr.update(visible=l_vis), gr.update(visible=t_vis), gr.update(visible=r_vis)
        updates[10] = gr.update(visible=c_vis)

    if mode == "循環評分賽 (ELO)":
        if state["current_round"] > state["total_rounds"]:
            set_updates("🎉 ELO 循環賽結束！這是最終排名。🎉")
        elif state["current_match_index"] >= len(state["matchups_this_round"]):
            state["current_round"] += 1
            if state["current_round"] > state["total_rounds"]:
                return display_match(state)
            state["matchups_this_round"] = create_swiss_pairings(state)
            state["current_match_index"] = 0
            if not state["matchups_this_round"]:
                set_updates("所有可能的配對均已完成，比賽結束！")
                state["current_round"] = state["total_rounds"] + 1
        
        if state["current_round"] <= state["total_rounds"] and state["matchups_this_round"]:
            match = state["matchups_this_round"][state["current_match_index"]]
            p1, p2 = match
            info_text = f"第 {state['current_round']}/{state['total_rounds']} 輪 - 第 {state['current_match_index'] + 1}/{len(state['matchups_this_round'])} 場"
            set_updates(info_text, True, True, True, is_video_file(p1) or is_video_file(p2))
            updates[2], updates[3] = gr.update(value=p1, label="選項 A", visible=True), gr.update(value=p2, label="選項 B", visible=True)

        ranking_df = pd.DataFrame([{"名稱": state["original_filenames"].get(p, "N/A"), "ELO分數": d["elo"], "積分": d["score"], "已賽場次": d["matches"]} for p, d in state["players"].items()]).sort_values(by="ELO分數", ascending=False).reset_index(drop=True)
        updates[7] = gr.update(value=ranking_df, visible=True)

    elif mode == "單淘汰賽":
        if state["current_match_index"] >= len(state["matchups"]):
            winners = [p for p, d in state["players"].items() if d["status"] == "winner"]
            if len(winners) == 1:
                winner_file, winner_name = winners[0], state["original_filenames"].get(winners[0], "N/A")
                
                # **[FIXED]** Assign the winner a higher rank order than any loser.
                state["players"][winner_file]['eliminated_in_round'] = state["round"] + 1
                
                ranking_data = [{"名稱": state["original_filenames"].get(p, "N/A"), "rank_order": d.get("eliminated_in_round", 0)} for p,d in state["players"].items()]
                ranking_df = pd.DataFrame(ranking_data).sort_values(by="rank_order", ascending=False)
                ranking_df["排名"] = range(1, len(ranking_df) + 1)
                set_updates("🎉 總冠軍出爐！ 🎉")
                updates[7] = gr.update(value=ranking_df[["排名", "名稱"]], visible=True)
                if is_video_file(winner_file): updates[8] = gr.update(value=winner_file, label=f"總冠軍：{winner_name}", visible=True)
                else: updates[9] = gr.update(value=winner_file, label=f"總冠軍：{winner_name}", visible=True)
                return (state,) + tuple(updates[1:])

            state["round"] += 1; state["current_match_index"] = 0; random.shuffle(winners)
            for p in winners: state["players"][p]["status"] = "active"
            state["matchups"] = list(zip(winners[::2], winners[1::2]))
            if len(winners) % 2 != 0: state["players"][winners[-1]]["status"] = "winner"
        
        if state["current_match_index"] < len(state["matchups"]):
            p1, p2 = state["matchups"][state["current_match_index"]]
            info_text = f"第 {state['round']} 輪 - 第 {state['current_match_index'] + 1}/{len(state['matchups'])} 場"
            set_updates(info_text, True, False, True, is_video_file(p1) or is_video_file(p2))
            updates[2], updates[3] = gr.update(value=p1, label="選項 A", visible=True), gr.update(value=p2, label="選項 B", visible=True)

    return (state,) + tuple(updates[1:])

def vote(outcome, state):
    if not isinstance(state, dict): return (state,) + (gr.update(),) * 10
    mode = state["mode"]
    
    if mode == "循環評分賽 (ELO)":
        p1, p2 = state["matchups_this_round"][state["current_match_index"]]
        state["match_history"].add(tuple(sorted((p1, p2)))) # Record match
        if outcome == 'A': result, score1, score2 = 1.0, 1.0, 0.0
        elif outcome == 'B': result, score1, score2 = 0.0, 0.0, 1.0
        else: result, score1, score2 = 0.5, 0.5, 0.5
        
        elo1, elo2 = calculate_elo(state["players"][p1]["elo"], state["players"][p2]["elo"], result)
        state["players"][p1].update({"elo": elo1, "score": state["players"][p1]["score"] + score1, "matches": state["players"][p1]["matches"] + 1})
        state["players"][p2].update({"elo": elo2, "score": state["players"][p2]["score"] + score2, "matches": state["players"][p2]["matches"] + 1})
        state["current_match_index"] += 1

    elif mode == "單淘汰賽" and outcome != 'TIE':
        winner_idx = 0 if outcome == 'A' else 1
        winner, loser = state["matchups"][state["current_match_index"]][winner_idx], state["matchups"][state["current_match_index"]][1 - winner_idx]
        state["players"][winner]["status"] = "winner"
        state["players"][loser].update({"status": "eliminated", "eliminated_in_round": state["round"]})
        state["current_match_index"] += 1
    return display_match(state)

# --- Gradio UI ---
SUPPORTED_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.jpg', '.jpeg', '.png', '.bmp', '.webp']
with gr.Blocks(theme=gr.themes.Soft(), css="footer {display: none !important}") as demo:
    state = gr.State()
    gr.Markdown("# 🏆 媒體競技場 (專家模式) 🏆")
    with gr.Row():
        with gr.Column(scale=1):
            tournament_type_selector = gr.Radio(["單淘汰賽", "循環評分賽 (ELO)"], label="選擇比賽模式", value="單淘汰賽")
            elo_rounds_input = gr.Number(label="循環賽總輪次 (建議3-7輪)", value=5, precision=0, visible=False)
        with gr.Column(scale=2):
            folder_selector = gr.File(label="選擇或拖放媒體資料夾", file_count="directory", file_types=["video", "image"])

    def toggle_elo_rounds_visibility(choice):
        return gr.update(visible=(choice == "循環評分賽 (ELO)"))
    tournament_type_selector.change(fn=toggle_elo_rounds_visibility, inputs=tournament_type_selector, outputs=elo_rounds_input)

    gr.Markdown("---")
    info_text = gr.Markdown("請選擇模式並上傳資料夾。")
    custom_video_controls = gr.HTML("""<div id="custom-video-controls" style="display: flex; justify-content: center; align-items: center; gap: 20px; margin-bottom: 10px;"><button id="play-pause-btn" class="gr-button gr-button-sm gr-button-secondary">▶️ 同步播放</button><input type="range" id="timeline-slider" style="width: 50%;" value="0" step="0.1"></div>""", visible=False)
    with gr.Row():
        left_media_display = gr.Video(elem_id="left-media-display", label="選項 A", visible=False, interactive=False)
        right_media_display = gr.Video(elem_id="right-media-display", label="選項 B", visible=False, interactive=False)
    with gr.Row(elem_id="vote-buttons"):
        left_btn = gr.Button("👈 選擇 A", visible=False, variant="secondary")
        tie_btn = gr.Button("平手", visible=False)
        right_btn = gr.Button("選擇 B 👉", visible=False, variant="secondary")
    gr.Markdown("---"); gr.Markdown("### 排名")
    ranking_table = gr.DataFrame(headers=["排名", "名稱", "ELO分數", "積分", "已賽場次"], visible=False, interactive=False)
    final_winner_video = gr.Video(label="總冠軍", visible=False, interactive=False)
    final_winner_image = gr.Image(label="總冠軍", visible=False, interactive=False)

    outputs_list = [state, info_text, left_media_display, right_media_display, left_btn, tie_btn, right_btn, ranking_table, final_winner_video, final_winner_image, custom_video_controls]
    
    folder_selector.upload(fn=start_tournament, inputs=[folder_selector, tournament_type_selector, elo_rounds_input], outputs=outputs_list).then(fn=None, inputs=None, outputs=None, js=js_script)
    left_btn.click(fn=lambda s: vote('A', s), inputs=[state], outputs=outputs_list).then(fn=None, inputs=None, outputs=None, js=js_script)
    tie_btn.click(fn=lambda s: vote('TIE', s), inputs=[state], outputs=outputs_list).then(fn=None, inputs=None, outputs=None, js=js_script)
    right_btn.click(fn=lambda s: vote('B', s), inputs=[state], outputs=outputs_list).then(fn=None, inputs=None, outputs=None, js=js_script)

if __name__ == "__main__":
    demo.launch()
