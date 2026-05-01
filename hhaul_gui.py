#!/usr/bin/env python3
"""
Hamerschlag Haul - Dispatch Control GUI
Tkinter desktop app to dispatch the robot and send it home via HTTP REST API.
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import requests
import base64
from datetime import datetime

DEFAULT_PI_URL = "http://172.26.19.241:5000"
MAX_HISTORY = 8

# Label → destination name sent to /dispatch
LOCATIONS = {
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
}

# Destination name → (x_fraction, y_fraction) position on the map canvas (0–1)
MAP_WAYPOINTS = {
    "Entrance": (0.15, 0.80),
    "Lab 1":    (0.45, 0.35),
    "Lab 2":    (0.70, 0.35),
    "Office":   (0.60, 0.65),
}

MAP_W, MAP_H = 488, 240


class HHaulGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Hamerschlag Haul — Dispatch Control")
        self.root.geometry("520x960")
        self.root.resizable(False, False)
        self.root.configure(bg="#f5f5f5")

        self.pi_url = tk.StringVar(value=DEFAULT_PI_URL)
        self.dest_var = tk.StringVar()
        self.history = []
        self._map_photo = None

        self._build_ui()

    def _build_ui(self):
        pad = dict(padx=16)

        # --- Header ---
        header = tk.Frame(self.root, bg="#1a1a1a", height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="Hamerschlag Haul",
            bg="#1a1a1a", fg="white",
            font=("Helvetica", 15, "bold")
        ).place(x=16, rely=0.5, anchor="w")

        # --- Pi URL ---
        url_frame = tk.LabelFrame(
            self.root, text="Pi Address",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        url_frame.pack(fill="x", **pad, pady=(12, 4))

        url_row = tk.Frame(url_frame, bg="#f5f5f5")
        url_row.pack(fill="x", padx=8, pady=6)

        tk.Entry(
            url_row, textvariable=self.pi_url,
            font=("Courier", 11), relief="solid", bd=1,
            bg="white", fg="#222"
        ).pack(side="left", fill="x", expand=True, ipady=4)

        tk.Button(
            url_row, text="Test",
            command=self._test_connection,
            bg="#e0e0e0", fg="#222", relief="flat",
            font=("Helvetica", 10), padx=10,
            activebackground="#c8c8c8", cursor="hand2"
        ).pack(side="left", padx=(6, 0), ipady=4)

        # --- Status badge ---
        self.status_canvas = tk.Canvas(
            self.root, width=488, height=32,
            bg="#f5f5f5", highlightthickness=0
        )
        self.status_canvas.pack(padx=16, pady=(2, 4))
        self._draw_status("idle", "Ready")

        # --- Quick locations ---
        loc_frame = tk.LabelFrame(
            self.root, text="Quick Locations",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        loc_frame.pack(fill="x", **pad, pady=(4, 4))

        btn_row = tk.Frame(loc_frame, bg="#f5f5f5")
        btn_row.pack(fill="x", padx=8, pady=8)
        for label, dest in LOCATIONS.items():
            tk.Button(
                btn_row,
                text=f"{label}  {dest}",
                command=lambda d=dest: self._quick_dispatch(d),
                bg="#e8e8e8", fg="#222", relief="flat",
                font=("Helvetica", 10), padx=10,
                activebackground="#c8c8c8", cursor="hand2"
            ).pack(side="left", padx=(0, 6), ipady=5)

        # --- Dispatch ---
        dispatch_frame = tk.LabelFrame(
            self.root, text="Send to Destination",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        dispatch_frame.pack(fill="x", **pad, pady=(4, 4))

        dest_row = tk.Frame(dispatch_frame, bg="#f5f5f5")
        dest_row.pack(fill="x", padx=8, pady=(6, 4))

        self.dest_entry = tk.Entry(
            dest_row, textvariable=self.dest_var,
            font=("Helvetica", 12), relief="solid", bd=1,
            bg="white", fg="#222"
        )
        self.dest_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.dest_entry.bind("<Return>", lambda e: self._send_dispatch())

        self.dispatch_btn = tk.Button(
            dest_row, text="Dispatch →",
            command=self._send_dispatch,
            bg="#1a1a1a", fg="white", relief="flat",
            font=("Helvetica", 10, "bold"), padx=12,
            activebackground="#333", cursor="hand2"
        )
        self.dispatch_btn.pack(side="left", padx=(6, 0), ipady=5)

        self.return_btn = tk.Button(
            dispatch_frame, text="⟵  Return to Start",
            command=self._send_return,
            bg="#f0f0f0", fg="#333", relief="flat",
            font=("Helvetica", 11), pady=6,
            activebackground="#ddd", cursor="hand2"
        )
        self.return_btn.pack(fill="x", padx=8, pady=(0, 8))

        # --- History ---
        hist_frame = tk.LabelFrame(
            self.root, text="Recent Destinations",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        hist_frame.pack(fill="x", **pad, pady=(4, 4))

        self.hist_listbox = tk.Listbox(
            hist_frame, height=4,
            font=("Helvetica", 11),
            bg="white", fg="#222",
            selectbackground="#1a1a1a", selectforeground="white",
            relief="flat", bd=0, activestyle="none",
            cursor="hand2"
        )
        self.hist_listbox.pack(fill="x", padx=8, pady=6)
        self.hist_listbox.bind("<Double-Button-1>", self._resend_from_history)
        self.hist_listbox.bind("<Return>", self._resend_from_history)

        tk.Label(
            hist_frame, text="Double-click to re-dispatch",
            bg="#f5f5f5", fg="#aaa", font=("Helvetica", 8)
        ).pack(anchor="e", padx=8, pady=(0, 4))

        # --- Map ---
        map_frame = tk.LabelFrame(
            self.root, text="Map",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        map_frame.pack(fill="x", **pad, pady=(4, 4))

        map_toolbar = tk.Frame(map_frame, bg="#f5f5f5")
        map_toolbar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(
            map_toolbar, text="Click a waypoint to set destination",
            bg="#f5f5f5", fg="#888", font=("Helvetica", 8)
        ).pack(side="left")
        tk.Button(
            map_toolbar, text="⟳ Load Map",
            command=self._load_map,
            bg="#e0e0e0", fg="#222", relief="flat",
            font=("Helvetica", 9), padx=8,
            activebackground="#c8c8c8", cursor="hand2"
        ).pack(side="right", ipady=2)

        self.map_canvas = tk.Canvas(
            map_frame, width=MAP_W, height=MAP_H,
            bg="#2a2a2a", highlightthickness=0, cursor="crosshair"
        )
        self.map_canvas.pack(padx=8, pady=(0, 8))
        self._draw_map_placeholder()

        # --- Log ---
        log_frame = tk.LabelFrame(
            self.root, text="Log",
            bg="#f5f5f5", fg="#555", font=("Helvetica", 9),
            bd=1, relief="groove"
        )
        log_frame.pack(fill="both", expand=True, **pad, pady=(4, 12))

        self.log_box = scrolledtext.ScrolledText(
            log_frame, height=5,
            font=("Courier", 10),
            bg="#1a1a1a", fg="#aaaaaa",
            relief="flat", bd=0,
            state="disabled"
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_box.tag_config("ok", foreground="#6abf69")
        self.log_box.tag_config("err", foreground="#f28b82")
        self.log_box.tag_config("info", foreground="#aaaaaa")

        self._log("info", "Hamerschlag Haul dispatcher ready")

    # ------------------------------------------------------------------ status

    def _draw_status(self, state, text):
        c = self.status_canvas
        c.delete("all")
        colors = {"idle": "#6abf69", "busy": "#f9a825", "offline": "#888"}
        dot_color = colors.get(state, "#888")
        c.create_oval(8, 10, 20, 22, fill=dot_color, outline="")
        c.create_text(28, 16, text=text, anchor="w",
                      font=("Helvetica", 10), fill="#555")

    # --------------------------------------------------------------------- map

    def _draw_map_placeholder(self):
        self.map_canvas.delete("all")
        self.map_canvas.create_text(
            MAP_W // 2, MAP_H // 2 - 12,
            text="No map loaded", fill="#555", font=("Helvetica", 11)
        )
        self.map_canvas.create_text(
            MAP_W // 2, MAP_H // 2 + 10,
            text="Press ⟳ Load Map to fetch from Pi",
            fill="#444", font=("Helvetica", 9)
        )
        self._draw_map_waypoints()

    def _draw_map_waypoints(self):
        for name, (fx, fy) in MAP_WAYPOINTS.items():
            x = int(fx * MAP_W)
            y = int(fy * MAP_H)
            r = 9
            tag = f"wp_{name.replace(' ', '_')}"
            self.map_canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill="#1a1a1a", outline="#6abf69", width=2,
                tags=(tag, "waypoint")
            )
            self.map_canvas.create_text(
                x, y - r - 6, text=name,
                fill="#e0e0e0", font=("Helvetica", 8, "bold"),
                tags=(tag, "waypoint")
            )
            self.map_canvas.tag_bind(tag, "<Button-1>",
                                     lambda e, d=name: self._select_from_map(d))
            self.map_canvas.tag_bind(tag, "<Enter>",
                                     lambda e, t=tag: self._wp_hover(t, True))
            self.map_canvas.tag_bind(tag, "<Leave>",
                                     lambda e, t=tag: self._wp_hover(t, False))

    def _wp_hover(self, tag, entering):
        for item in self.map_canvas.find_withtag(tag):
            if self.map_canvas.type(item) == "oval":
                self.map_canvas.itemconfig(
                    item, fill="#333333" if entering else "#1a1a1a"
                )

    def _select_from_map(self, dest):
        self.dest_var.set(dest)
        self._log("info", f"Map: selected '{dest}' — press Dispatch or Enter to send")

    def _load_map(self):
        self._log("info", "Fetching map from Pi...")
        threading.Thread(target=self._do_load_map, daemon=True).start()

    def _do_load_map(self):
        try:
            r = requests.get(self._base_url() + "/map", timeout=8)
            if r.ok:
                img_data = base64.b64encode(r.content).decode()
                self.root.after(0, self._set_map_image, img_data)
            else:
                self.root.after(0, self._log, "err", f"Map fetch failed: {r.status_code}")
        except requests.exceptions.ConnectionError:
            self.root.after(0, self._log, "err", "Could not reach Pi for map")
        except Exception as e:
            self.root.after(0, self._log, "err", f"Map error: {e}")

    def _set_map_image(self, img_data):
        try:
            photo = tk.PhotoImage(data=img_data)
            self._map_photo = photo  # keep reference — GC will drop it otherwise
            self.map_canvas.delete("all")
            self.map_canvas.create_image(0, 0, anchor="nw", image=photo)
            self._draw_map_waypoints()
            self._log("ok", "Map loaded")
        except Exception as e:
            self._log("err", f"Could not display map image: {e}")

    # ----------------------------------------------------------------- actions

    def _quick_dispatch(self, dest):
        self.dest_var.set(dest)
        self._send_dispatch()

    def _log(self, level, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line, level)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.dispatch_btn.configure(state=state)
        self.return_btn.configure(state=state)

    def _add_history(self, dest):
        if dest in self.history:
            self.history.remove(dest)
        self.history.insert(0, dest)
        if len(self.history) > MAX_HISTORY:
            self.history.pop()
        self.hist_listbox.delete(0, "end")
        for d in self.history:
            self.hist_listbox.insert("end", f"  {d}")

    def _resend_from_history(self, event=None):
        sel = self.hist_listbox.curselection()
        if not sel:
            return
        dest = self.history[sel[0]]
        self.dest_var.set(dest)
        self._send_dispatch()

    def _base_url(self):
        return self.pi_url.get().strip().rstrip("/")

    def _send_dispatch(self):
        dest = self.dest_var.get().strip()
        if not dest:
            self._log("err", "No destination entered")
            return
        self._set_busy(True)
        self._draw_status("busy", f"Dispatching to: {dest}")
        threading.Thread(target=self._do_dispatch, args=(dest,), daemon=True).start()

    def _do_dispatch(self, dest):
        try:
            url = self._base_url() + "/dispatch"
            r = requests.post(url, json={"destination": dest}, timeout=5)
            if r.ok:
                data = r.json() if r.content else {}
                msg = data.get("message", "Accepted")
                self.root.after(0, self._log, "ok", f"Dispatched to '{dest}' — {msg}")
                self.root.after(0, self._draw_status, "busy", f"Heading to {dest}")
                self.root.after(0, self._add_history, dest)
                self.root.after(0, self.dest_var.set, "")
            else:
                self.root.after(0, self._log, "err", f"Server error {r.status_code}")
                self.root.after(0, self._draw_status, "offline", f"Error {r.status_code}")
        except requests.exceptions.ConnectionError:
            self.root.after(0, self._log, "err", "Could not reach Pi — connection refused")
            self.root.after(0, self._draw_status, "offline", "Unreachable")
        except requests.exceptions.Timeout:
            self.root.after(0, self._log, "err", "Request timed out")
            self.root.after(0, self._draw_status, "offline", "Timeout")
        except Exception as e:
            self.root.after(0, self._log, "err", str(e))
            self.root.after(0, self._draw_status, "offline", "Error")
        finally:
            self.root.after(0, self._set_busy, False)

    def _send_return(self):
        self._set_busy(True)
        self._draw_status("busy", "Returning to start...")
        threading.Thread(target=self._do_return, daemon=True).start()

    def _do_return(self):
        try:
            url = self._base_url() + "/return"
            r = requests.post(url, timeout=5)
            if r.ok:
                self.root.after(0, self._log, "ok", "Return to start accepted")
                self.root.after(0, self._draw_status, "busy", "Returning to start")
            else:
                self.root.after(0, self._log, "err", f"Server error {r.status_code}")
                self.root.after(0, self._draw_status, "offline", f"Error {r.status_code}")
        except requests.exceptions.ConnectionError:
            self.root.after(0, self._log, "err", "Could not reach Pi")
            self.root.after(0, self._draw_status, "offline", "Unreachable")
        except Exception as e:
            self.root.after(0, self._log, "err", str(e))
            self.root.after(0, self._draw_status, "offline", "Error")
        finally:
            self.root.after(0, self._set_busy, False)

    def _test_connection(self):
        self._draw_status("busy", "Testing...")
        threading.Thread(target=self._do_test, daemon=True).start()

    def _do_test(self):
        try:
            url = self._base_url() + "/status"
            r = requests.get(url, timeout=4)
            if r.ok:
                data = r.json() if r.content else {}
                state = data.get("state", "ok")
                self.root.after(0, self._log, "ok", f"Connected — robot state: {state}")
                self.root.after(0, self._draw_status, "idle", f"Connected ({state})")
            else:
                self.root.after(0, self._log, "err", f"Pi responded {r.status_code}")
                self.root.after(0, self._draw_status, "offline", f"Error {r.status_code}")
        except requests.exceptions.ConnectionError:
            self.root.after(0, self._log, "err", "No response from Pi")
            self.root.after(0, self._draw_status, "offline", "Unreachable")
        except Exception as e:
            self.root.after(0, self._log, "err", str(e))
            self.root.after(0, self._draw_status, "offline", "Error")


if __name__ == "__main__":
    root = tk.Tk()
    app = HHaulGUI(root)
    root.mainloop()
