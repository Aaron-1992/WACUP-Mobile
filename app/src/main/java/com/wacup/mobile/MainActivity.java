package com.wacup.mobile;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.View;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

import com.wacup.mobile.playlist.Playlist;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.Skin;
import com.wacup.mobile.ui.EqWindowView;
import com.wacup.mobile.ui.FileBrowser;
import com.wacup.mobile.ui.MainWindowView;
import com.wacup.mobile.ui.PlaylistWindowView;
import com.wacup.mobile.ui.DesktopLayout;

import java.io.File;
import java.util.List;

/**
 * Hosts the three skin windows. There is no Material UI here on purpose: the app is
 * the skin, and every command lives on the skin's own controls (tap the title bar
 * for the menu).
 */
public class MainActivity extends Activity implements MusicEngine.Listener,
        MainWindowView.Callbacks,
        PlaylistWindowView.Callbacks,
        EqWindowView.Callbacks,
        DesktopLayout.Listener {

    private static final int REQ_STORAGE = 1;

    private MusicEngine engine;
    private Skin skin;

    private MainWindowView mainWindow;
    private EqWindowView eqWindow;
    private PlaylistWindowView playlistWindow;
    private DesktopLayout layout;

    private final Handler ticker = new Handler(Looper.getMainLooper());
    private final Runnable tickTask = new Runnable() {
        @Override
        public void run() {
            mainWindow.tick();
            playlistWindow.invalidate();
            ticker.postDelayed(this, 250);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            // Same mechanism Google Maps uses while navigating: our own window is
            // allowed to draw over the keyguard, without unlocking the device.
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }

        engine = MusicEngine.get(this);
        engine.addListener(this);

        mainWindow = new MainWindowView(this, engine);
        eqWindow = new EqWindowView(this, engine);
        playlistWindow = new PlaylistWindowView(this, engine);
        playlistWindow.setVisibleRows(6);

        mainWindow.setCallbacks(this);
        playlistWindow.setCallbacks(this);
        eqWindow.setCallbacks(this);

        layout = new DesktopLayout(this, mainWindow, eqWindow, playlistWindow);
        layout.setListener(this);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF101010);
        root.addView(layout, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);

        applySkin(loadSavedSkin());
        syncWindowState();
        restoreLastPlaylist();
        requestStoragePermission();
        startPlaybackService();
    }

    @Override
    protected void onResume() {
        super.onResume();
        ticker.post(tickTask);
        refreshWindows();
    }

    @Override
    protected void onPause() {
        super.onPause();
        ticker.removeCallbacks(tickTask);
    }

    @Override
    protected void onDestroy() {
        engine.removeListener(this);
        super.onDestroy();
    }

    private void startPlaybackService() {
        try {
            startService(new Intent(this, PlaybackService.class));
        } catch (Exception ignored) {
            // Playback still works without the session; only the notification is lost.
        }
    }

    // ------------------------------------------------------------- skin state

    private Skin loadSavedSkin() {
        File saved = engine.lastSkin();
        if (saved != null) {
            try {
                return Skin.load(saved);
            } catch (Exception e) {
                toast("Saved skin could not be loaded: " + e.getMessage());
            }
        }
        return Skin.base();
    }

    private void applySkin(Skin newSkin) {
        this.skin = newSkin;
        mainWindow.setSkin(newSkin);
        eqWindow.setSkin(newSkin);
        playlistWindow.setSkin(newSkin);
        refreshWindows();
    }

    private void refreshWindows() {
        mainWindow.invalidate();
        eqWindow.invalidate();
        playlistWindow.invalidate();
    }

    private void restoreLastPlaylist() {
        File last = engine.lastPlaylist();
        if (last == null || !last.isFile()) return;
        try {
            Playlist loaded = Playlist.read(last);
            engine.playlist().clear();
            engine.playlist().addAll(loaded.tracks);
            engine.setQueue(loaded.tracks, 0);
            playlistWindow.invalidate();
        } catch (Exception e) {
            toast("Could not reopen " + last.getName());
        }
    }

    // --------------------------------------------------------------- commands

    @Override
    public void onTransport(int button) {
        switch (button) {
            case 0: engine.previous(); break;
            case 1:
            case 2: engine.togglePlayPause(); break;
            case 3: engine.stop(); break;
            case 4: engine.next(); break;
            default: showMenu(); break;
        }
        refreshWindows();
    }

    @Override
    public void onSeek(float fraction) {
        engine.seekFraction(fraction);
        refreshWindows();
    }

    @Override
    public void onVolume(int percent) {
        engine.setVolumePercent(percent);
        refreshWindows();
    }

    @Override
    public void onToggleEq() {
        layout.toggleWindow(DesktopLayout.EQ);
        syncWindowState();
    }

    @Override
    public void onTogglePlaylist() {
        layout.toggleWindow(DesktopLayout.PLAYLIST);
        syncWindowState();
    }

    private void syncWindowState() {
        mainWindow.setWindowState(layout.isWindowVisible(DesktopLayout.EQ),
                layout.isWindowVisible(DesktopLayout.PLAYLIST));
    }

    // ------------------------------------------------------- window management

    @Override
    public void onTitleTap(int kind) {
        if (kind == DesktopLayout.MAIN) {
            showMenu();
        } else {
            showWindowsMenu();
        }
    }

    @Override
    public void onToggleShade(int kind) {
        if (kind == DesktopLayout.MAIN) {
            layout.setShaded(kind, !layout.isShaded(kind));
            toast(layout.isShaded(kind) ? "Windowshade" : "Window expanded");
        }
    }

    @Override
    public void onWindowMoved() {
        // Positions are persisted by the layout.
    }

    private void showWindowsMenu() {
        final boolean[] checked = {
                layout.isWindowVisible(DesktopLayout.EQ),
                layout.isWindowVisible(DesktopLayout.PLAYLIST)
        };
        final String[] names = {"Equaliser window", "Playlist window"};

        new android.app.AlertDialog.Builder(this)
                .setTitle("Windows")
                .setMultiChoiceItems(names, checked,
                        new android.content.DialogInterface.OnMultiChoiceClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface d, int which,
                                                boolean isChecked) {
                                int kind = which == 0 ? DesktopLayout.EQ : DesktopLayout.PLAYLIST;
                                layout.setWindowVisible(kind, isChecked);
                                syncWindowState();
                            }
                        })
                .setPositiveButton("Done", null)
                .setNeutralButton(layout.isShaded(DesktopLayout.MAIN) ? "Expand" : "Shade",
                        new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface d, int which) {
                                layout.setShaded(DesktopLayout.MAIN,
                                        !layout.isShaded(DesktopLayout.MAIN));
                            }
                        })
                .setNegativeButton("Reset layout", new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface d, int which) {
                        layout.resetPositions();
                        toast("Window positions reset");
                    }
                })
                .show();
    }

    @Override
    public void onShuffle() {
        engine.toggleShuffle();
        refreshWindows();
    }

    @Override
    public void onRepeat() {
        engine.cycleRepeat();
        refreshWindows();
    }

    @Override
    public void onPlayTrack(int index) {
        if (index < 0 || index >= engine.playlist().size()) return;
        engine.playIndex(index);
        refreshWindows();
    }

    @Override
    public void onTrackMenu(int index) {
        showMenu();
    }

    @Override
    public void onToggleEqEnabled() {
        engine.toggleEq();
        refreshWindows();
    }

    @Override
    public void onCyclePreset() {
        eqWindow.nextPreset();
    }

    @Override
    public void onMenu() {
        showMenu();
    }

    @Override
    public void onPlayerStateChanged() {
        refreshWindows();
    }

    // ------------------------------------------------------------------- menu

    private void showMenu() {
        final String[] items = {
                "Add files…",
                "Add folder…",
                "Load playlist (.m3u / .pls)…",
                "Save playlist…",
                "Load skin (.wsz)…",
                "Use built-in skin",
                "Clear playlist",
                "Windows…",
                "Grant all-files access",
                "About"
        };

        new android.app.AlertDialog.Builder(this)
                .setTitle("WACUP Mobile")
                .setItems(items, new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        switch (which) {
                            case 0: addFiles(); break;
                            case 1: addFolder(); break;
                            case 2: loadPlaylist(); break;
                            case 3: savePlaylist(); break;
                            case 4: loadSkin(); break;
                            case 5: useBaseSkin(); break;
                            case 6: clearPlaylist(); break;
                            case 7: showWindowsMenu(); break;
                            case 8: requestAllFiles(); break;
                            default: showAbout(); break;
                        }
                    }
                })
                .show();
    }

    private void addFiles() {
        FileBrowser.pickAudio(this, engine.lastFolder(), new FileBrowser.OnFile() {
            @Override
            public void onFile(File file) {
                if (file == null) return;
                addTracks(java.util.Collections.singletonList(Track.of(file)), false);
                engine.setLastFolder(file.getParentFile());
            }
        });
    }

    private void addFolder() {
        FileBrowser.pickFolder(this, engine.lastFolder(), new FileBrowser.OnFolder() {
            @Override
            public void onFolder(File dir) {
                if (dir == null) return;
                List<Track> found = Playlist.scanFolder(dir, true);
                engine.setLastFolder(dir);
                if (found.isEmpty()) {
                    toast("No audio files in " + dir.getName());
                    return;
                }
                addTracks(found, engine.playlist().size() == 0);
            }
        });
    }

    private void addTracks(List<Track> tracks, boolean autoPlay) {
        boolean wasEmpty = engine.playlist().size() == 0;
        engine.playlist().addAll(tracks);
        int start = wasEmpty ? 0 : engine.currentIndex();
        engine.setQueue(engine.playlist().tracks, Math.max(0, start));
        if (autoPlay && wasEmpty) engine.playIndex(0);
        toast(tracks.size() + " track(s) added");
        refreshWindows();
    }

    private void loadPlaylist() {
        FileBrowser.pickPlaylist(this, engine.lastFolder(), new FileBrowser.OnFile() {
            @Override
            public void onFile(File file) {
                if (file == null) return;
                try {
                    Playlist loaded = Playlist.read(file);
                    if (loaded.size() == 0) {
                        toast("That playlist is empty");
                        return;
                    }
                    engine.setQueue(loaded.tracks, 0);
                    engine.setLastPlaylist(file);
                    engine.setLastFolder(file.getParentFile());
                    toast(loaded.size() + " tracks loaded from " + file.getName());
                    refreshWindows();
                } catch (Exception e) {
                    toast("Could not read playlist: " + e.getMessage());
                }
            }
        });
    }

    private void savePlaylist() {
        if (engine.playlist().size() == 0) {
            toast("Playlist is empty");
            return;
        }
        final EditText input = new EditText(this);
        input.setText("wacup-playlist.m3u");
        new android.app.AlertDialog.Builder(this)
                .setTitle("Save playlist as")
                .setView(input)
                .setPositiveButton("Save", new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        String name = input.getText().toString().trim();
                        if (name.isEmpty()) name = "wacup-playlist.m3u";
                        if (!name.contains(".")) name = name + ".m3u";
                        File dir = new File(Environment.getExternalStorageDirectory(), "Music");
                        if (!dir.isDirectory()) dir = getExternalFilesDir(null);
                        File target = new File(dir, name);
                        Playlist out = new Playlist();
                        out.addAll(engine.playlist().tracks);
                        try {
                            out.write(target);
                            engine.setLastPlaylist(target);
                            toast("Saved to " + target.getAbsolutePath());
                        } catch (Exception e) {
                            toast("Save failed: " + e.getMessage());
                        }
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void loadSkin() {
        FileBrowser.pickSkin(this, engine.lastFolder(), new FileBrowser.OnFile() {
            @Override
            public void onFile(File file) {
                if (file == null) return;
                try {
                    Skin loaded = Skin.load(file);
                    applySkin(loaded);
                    engine.setLastSkin(file);
                    toast("Skin: " + loaded.name);
                } catch (Exception e) {
                    toast("Not a usable skin: " + e.getMessage());
                }
            }
        });
    }

    private void useBaseSkin() {
        applySkin(Skin.base());
        engine.setLastSkin(null);
        toast("Built-in skin");
    }

    private void clearPlaylist() {
        engine.stop();
        engine.playlist().clear();
        engine.setQueue(new java.util.ArrayList<Track>(), 0);
        refreshWindows();
    }

    private void requestAllFiles() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                startActivity(new Intent(
                        Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                return;
            } catch (Exception ignored) {
                // fall through to the generic screen
            }
            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        } else {
            toast("Not needed on this Android version");
        }
    }

    private void showAbout() {
        new android.app.AlertDialog.Builder(this)
                .setTitle("WACUP Mobile 0.1")
                .setMessage("A native Android player built around classic Winamp 2.x skins.\n\n"
                        + "• Load .wsz skins from any folder\n"
                        + "• Reads and writes .m3u / .m3u8 / .pls playlists\n"
                        + "• 10-band equaliser\n"
                        + "• Media notification, lock-screen and Bluetooth controls\n\n"
                        + "Skin: " + skin.name + "\n"
                        + "Not affiliated with Winamp, WACUP or Llama Group. "
                        + "Skins are the property of their authors.")
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }

    // ------------------------------------------------------------ permissions

    private void requestStoragePermission() {
        String permission = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                ? Manifest.permission.READ_MEDIA_AUDIO
                : Manifest.permission.READ_EXTERNAL_STORAGE;
        if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{permission}, REQ_STORAGE);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_STORAGE && grantResults.length > 0
                && grantResults[0] != PackageManager.PERMISSION_GRANTED) {
            toast("Without storage access only the app folder is browsable — "
                    + "use \"Grant all-files access\" in the menu");
        }
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    @Override
    public void onBackPressed() {
        if (layout.isWindowVisible(DesktopLayout.PLAYLIST)) {
            layout.setWindowVisible(DesktopLayout.PLAYLIST, false);
            syncWindowState();
            return;
        }
        super.onBackPressed();
    }
}
