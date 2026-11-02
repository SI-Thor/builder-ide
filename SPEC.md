# Casey's agent's spec (2026-11-01, condensed by the director): "End-to-End Vibecoding & Autonomous Playtesting Sandbox"
Zero-cloud. ProArt (Windows 11 client: game engine UE5/Godot, runtime glTF importer, GStreamer H.264 HW encoder)
+ Thor (headless Ubuntu 24.04, Celery/Redis task worker, nvidia-docker containers), over a direct 10 GbE link.
Phase 1 fabric: direct Cat6A ProArt<->Thor, static IPs 10.10.10.1/.2; monitor PbP (ProArt DP, Thor HDMI);
  input-leap KVM; `systemctl set-default multi-user.target` on the Thor; VS Code Remote-SSH.
Phase 2 storage: Thor NVMe ext4 exported by Samba ([gamedev_share], writable, guest ok, strict locking=no,
  sendfile) mounted as Z:\ on Windows; a watchdog daemon on the share catches `*.json` with
  action=generate_room and runs `docker exec blender_worker blender --background --python bake_pipeline.py -- <json>`.
Phase 3 generation: "vLLM or multi-view Gaussian models like LGM" -> raw .gltf; ComfyUI API -> 4K tileable
  normal/roughness/albedo; headless Blender: import raw mesh, Decimate ratio 0.35, pack PBR, export
  final_delivery_<room_id>.gltf (GLTF_EMBEDDED); "bone transformations from local skeletal generation".
Phase 4 hot-load: engine runtime polls Z:\ for final_delivery_*.gltf, loads via glTFRuntime, spawns an actor,
  broadcasts OnRoomGenerationComplete to the tester.
Phase 5 autonomous QA: "Aura Autopilot" (claimed repo ramenvr/autopilot, Python/C++ API) runs on the Thor;
  ProArt streams the viewport as H.264 RTP/UDP (d3d11screencapturesrc ! nvenc ! rtph264pay ! udpsink 10.10.10.2:5004);
  the agent (VLM) sends virtual inputs back, explores the new room with a prompt ("check collision clipping, jump
  floating debris, report camera occlusion / navmesh drops"), writes qa_report_<room>.json to the share.
