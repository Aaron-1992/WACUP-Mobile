package com.wacup.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

import com.wacup.mobile.playlist.Playlist;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.Skin;
import com.wacup.mobile.ui.DesktopLayout;
import com.wacup.mobile.ui.EqWindowView;
import com.wacup.mobile.ui.FileBrowser;
import com.wacup.mobile.ui.MainWindowView;
import com.wacup.mobile.ui.PlaylistWindowView;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * Hosts the Winamp-style windows. There is no Material UI by design: the skin is
 * the UI, and every command is reachable from the windows themselves.
 */
public class MainActivity extends Activity implements
        MusicEngine.Listener,
        MainWindowView.Callbacks,
        EqWindowView.Callbacks,
        PlaylistWindowView.Callbacks,
        DesktopLayout.Listener {

    private static final int REQ_STORAGE = 1;

    private static final String[] PRESETS = {
            "Flat", "Rock", "Pop", "Jazz", "Classical", "Dance", "Bass", "Treble", "Vocal"
    };
    private static final float[][] PRESET_GAINS = {
            {0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
            {5, 4, 3, 1, -1, -1, 0, 2, 3, 4},
            {-1, 2, 4, 4, 1, -1, -1, 1, 2, 2},
            {3, 2, 1, 2, -1, -1, 0, 1, 2, 3},
            {4, 3, 2, 1, -1, -1, 0, 2, 3, 4},
            {6, 5, 2, 0, 0, -2, -3, -3, 0, 1},
            {7, 6, 4, 2, 0, 0, 0, 0, 0, 0},
            {-3, -2, 0, 1, 2, 3, 4, 5, 6, 6},
            {-2, -1, 0, 2, 4, 4, 3, 1, 0, -1}
    };

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
            // The same mechanism Google Maps uses: our own window may draw over the
            // keyguard without unlocking the device.
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }

        engine = MusicEngine.get(this);
        engine.addListener(this);

        mainWindow = new MainWindowView(this, engine);
        eqWindow = new EqWindowView(this, engine);
        playlistWindow = new PlaylistWindowView(this, engine);

        mainWindow.setCallbacks(this);
        eqWindow.setCallbacks(this);
        playlistWindow.setCallbacks(this);

        layout = new DesktopLayout(this, mainWindow, eqWindow, playlistWindow);
        layout.setListener(this);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF0B0B0B);
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
            // Playback works without the session; only the notification is lost.
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
        skin = newSkin;
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
            engine.setQueue(loaded.tracks, 0);
            playlistWindow.invalidate();
        } catch (Exception e) {
            toast("Could not reopen " + last.getName());
        }
    }

    private void syncWindowState() {
        mainWindow.setWindowState(layout.isWindowVisible(DesktopLayout.EQ),
                layout.isWindowVisible(DesktopLayout.PLAYLIST));
    }

    // ------------------------------------------------------- main window input

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
    public void onSlider(boolean volume, float fraction) {
        if (volume) {
            engine.setVolumePercent(Math.round(fraction * 100f));
            refreshWindows();
        }
    }

    @Override
    public void onToggleEqWindow() {
        layout.toggleWindow(DesktopLayout.EQ);
        syncWindowState();
    }

    @Override
    public void onTogglePlaylistWindow() {
        layout.toggleWindow(DesktopLayout.PLAYLIST);
        syncWindowState();
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
    public void onMenu() {
        showMenu();
    }

    @Override
    public void onTitleButton(int which) {
        switch (which) {
            case MainWindowView.TITLE_SHADE:
                layout.setShaded(DesktopLayout.MAIN,
                        !layout.isShaded(DesktopLayout.MAIN));
                break;
            case MainWindowView.TITLE_MINIMIZE:
                layout.setWindowVisible(DesktopLayout.PLAYLIST, false);
                layout.setWindowVisible(DesktopLayout.EQ, false);
                syncWindowState();
                toast("Windows hidden — tap the title bar to bring them back");
                break;
            case MainWindowView.TITLE_CLOSE:
                showMenu();
                break;
            default:
                showMenu();
                break;
        }
    }

    // --------------------------------------------------- equaliser window input

    @Override
    public void onToggleEqEnabled() {
        engine.toggleEq();
        eqWindow.invalidate();
    }

    @Override
    public void onPresetMenu() {
        new AlertDialog.Builder(this)
                .setTitle("Equaliser preset")
                .setItems(PRESETS, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        for (int band = 0; band < PRESET_GAINS[which].length; band++) {
                            engine.setBandGain(band, PRESET_GAINS[which][band]);
                        }
                        if (!engine.eqEnabled()) engine.setEqEnabled(true);
                        eqWindow.invalidate();
                        toast(PRESETS[which]);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---------------------------------------------------- playlist window input

    @Override
    public void onPlayTrack(int index) {
        if (index < 0 || index >= engine.playlist().size()) return;
        engine.playIndex(index);
        refreshWindows();
    }

    @Override
    public void onTrackMenu(final int index) {
        final Track track = engine.playlist().get(index);
        if (track == null) return;
        new AlertDialog.Builder(this)
                .setTitle(track.title)
                .setItems(new String[]{"Play", "Remove from playlist", "Show file path"},
                        new DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which) {
                                if (which == 0) {
                                    engine.playIndex(index);
                                } else if (which == 1) {
                                    engine.playlist().removeAt(index);
                                    if (engine.playlist().size() == 0) {
                                        engine.stop();
                                        engine.setQueue(new ArrayList<Track>(), 0);
                                    } else {
                                        engine.setQueue(engine.playlist().tracks,
                                                Math.max(0, Math.min(index,
                                                        engine.playlist().size() - 1)));
                                    }
                                    toast("Removed");
                                } else {
                                    toast(track.file.getAbsolutePath());
                                }
                                refreshWindows();
                            }
                        })
                .show();
    }

    @Override
    public void onListMenu() {
        showMenu();
    }

    // ------------------------------------------------------ desktop window mgmt

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
        layout.setShaded(kind, !layout.isShaded(kind));
        if (kind == DesktopLayout.MAIN) {
            toast(layout.isShaded(kind) ? "Windowshade" : "Expanded");
        }
    }

    @Override
    public void onWindowMoved() {
        // persisted by the layout
    }

    @Override
    public void onFitChanged(boolean autoFit) {
        toast(autoFit ? "Auto-fit on" : "Free positioning — drag windows anywhere");
    }

    @Override
    public void onPlayerStateChanged() {
        refreshWindows();
    }

    // ------------------------------------------------------------------- menus

    private void showWindowsMenu() {
        final boolean[] checked = {
                layout.isWindowVisible(DesktopLayout.EQ),
                layout.isWindowVisible(DesktopLayout.PLAYLIST),
                layout.isAutoFit()
        };
        final String[] names = {"Equaliser", "Playlist", "Auto-fit to screen"};

        new AlertDialog.Builder(this)
                .setTitle("Windows")
                .setMultiChoiceItems(names, checked,
                        new DialogInterface.OnMultiChoiceClickListener() {
                            @Override
                            public void onClick(DialogInterface d, int which, boolean on) {
                                if (which == 2) {
                                    if (on) {
                                        layout.fitToScreen();
                                    } else {
                                        toast("Drag a title bar to place windows");
                                    }
                                    return;
                                }
                                layout.setWindowVisible(
                                        which == 0 ? DesktopLayout.EQ : DesktopLayout.PLAYLIST, on);
                                syncWindowState();
                            }
                        })
                .setPositiveButton("Done", null)
                .setNeutralButton("Fit now", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        layout.fitToScreen();
                        toast("Windows re-arranged");
                    }
                })
                .setNegativeButton("Reset", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        layout.resetPositions();
                        toast("Layout reset");
                    }
                })
                .show();
    }

    private void showMenu() {
        String[] items = {
                "Add files…",
                "Add folder…",
                "Load playlist (.m3u / .pls)…",
                "Save playlist…",
                "Load skin (.wsz)…",
                "Use built-in skin",
                "Load included sample skin",
                "Windows…",
                "Equaliser preset…",
                "Clear playlist",
                "Grant all-files access",
                "About"
        };

        new AlertDialog.Builder(this)
                .setTitle(skin.name)
                .setItems(items, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        switch (which) {
                            case 0: addFiles(); break;
                            case 1: addFolder(); break;
                            case 2: loadPlaylist(); break;
                            case 3: savePlaylist(); break;
                            case 4: loadSkin(); break;
                            case 5: useBaseSkin(); break;
                            case 6: loadSampleSkin(); break;
                            case 7: showWindowsMenu(); break;
                            case 8: onPresetMenu(); break;
                            case 9: clearPlaylist(); break;
                            case 10: requestAllFiles(); break;
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
                List<Track> one = new ArrayList<>();
                one.add(Track.of(file));
                addTracks(one);
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
                addTracks(found);
            }
        });
    }

    private void addTracks(List<Track> tracks) {
        boolean wasEmpty = engine.playlist().size() == 0;
        List<Track> all = new ArrayList<>(engine.playlist().tracks);
        all.addAll(tracks);
        engine.setQueue(all, wasEmpty ? 0 : engine.currentIndex());
        if (wasEmpty) engine.playIndex(0);
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
                    toast(loaded.size() + " tracks from " + file.getName());
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
        new AlertDialog.Builder(this)
                .setTitle("Save playlist as")
                .setView(input)
                .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
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

    /** The .wsz bundled in assets/, handy before any files have been copied over. */
    private void loadSampleSkin() {
        try {
            Skin sample = Skin.fromAssets(this, "haruhi-suzumiya.wsz");
            applySkin(sample);
            engine.setLastSkin(null);
            toast("Sample skin loaded");
        } catch (Exception e) {
            toast("Sample skin failed: " + e.getMessage());
        }
    }

    private void useBaseSkin() {
        applySkin(Skin.base());
        engine.setLastSkin(null);
        toast("Built-in skin");
    }

    private void clearPlaylist() {
        engine.stop();
        engine.setQueue(new ArrayList<Track>(), 0);
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
                // fall through
            }
            startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
        } else {
            toast("Not needed on this Android version");
        }
    }

    private void showAbout() {
        new AlertDialog.Builder(this)
                .setTitle("WACUP Mobile 0.2")
                .setMessage("A native Android player built on classic Winamp 2.x skins.\n\n"
                        + "• Floating windows: drag by the title bar, double-tap to roll up\n"
                        + "• Auto-fit keeps every window on screen; drag to place freely\n"
                        + "• Skins from any folder: .wsz / .zip\n"
                        + "• .m3u / .m3u8 / .pls in and out\n"
                        + "• 10-band equaliser + presets\n"
                        + "• Media notification, lock screen, Bluetooth\n\n"
                        + "Skin: " + skin.name + "\n"
                        + "Not affiliated with Winamp, WACUP or Llama Group.")
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
            toast("Use \"Grant all-files access\" in the menu to browse all folders");
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
        if (layout.isWindowVisible(DesktopLayout.EQ)) {
            layout.setWindowVisible(DesktopLayout.EQ, false);
            syncWindowState();
            return;
        }
        super.onBackPressed();
    }
}
