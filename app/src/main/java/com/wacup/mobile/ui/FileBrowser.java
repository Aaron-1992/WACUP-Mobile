package com.wacup.mobile.ui;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Environment;

import com.wacup.mobile.playlist.Playlist;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * Plain-filesystem browser. Deliberately not SAF: with storage permission granted,
 * real paths are what .m3u/.pls playlists from a PC contain, and what a user in
 * developer mode expects. The app's own external folder always works as a fallback.
 */
public final class FileBrowser {

    public interface OnFile {
        void onFile(File file);
    }

    public interface OnFolder {
        void onFolder(File dir);
    }

    private FileBrowser() { }

    public static File defaultStart(Activity activity) {
        File music = new File(Environment.getExternalStorageDirectory(), "Music");
        if (music.isDirectory()) return music;
        File root = Environment.getExternalStorageDirectory();
        if (root.isDirectory()) return root;
        File own = activity.getExternalFilesDir(null);
        return own != null ? own : activity.getFilesDir();
    }

    public static void pickPlaylist(Activity activity, File start, OnFile callback) {
        pick(activity, start, "Load playlist", new Filter() {
            @Override
            public boolean accept(File f) {
                return Playlist.isPlaylist(f);
            }
        }, callback);
    }

    public static void pickSkin(Activity activity, File start, OnFile callback) {
        pick(activity, start, "Load skin (.wsz / .zip)", new Filter() {
            @Override
            public boolean accept(File f) {
                String n = f.getName().toLowerCase();
                return n.endsWith(".wsz") || n.endsWith(".zip") || n.endsWith(".wal");
            }
        }, callback);
    }

    public static void pickAudio(Activity activity, File start, OnFile callback) {
        pick(activity, start, "Add audio files", new Filter() {
            @Override
            public boolean accept(File f) {
                return Playlist.isAudio(f);
            }
        }, callback);
    }

    /** Picks a folder and returns it, so the caller can scan it recursively. */
    public static void pickFolder(Activity activity, File start, final OnFolder callback) {
        browse(activity, start, "Add folder", new Filter() {
            @Override
            public boolean accept(File f) {
                return false;
            }
        }, new OnFile() {
            @Override
            public void onFile(File file) {
                if (file != null && file.isDirectory()) callback.onFolder(file);
            }
        }, true);
    }

    private interface Filter {
        boolean accept(File file);
    }

    private static void pick(final Activity activity, File start, String title,
                             Filter filter, final OnFile callback) {
        browse(activity, start, title, filter, callback, false);
    }

    private static void browse(final Activity activity, File dir, final String title,
                               final Filter filter, final OnFile callback,
                               final boolean folderMode) {
        if (dir == null || !dir.isDirectory()) {
            showMessage(activity, "Folder not readable: " + dir);
            return;
        }

        final File current = dir;
        final List<File> entries = new ArrayList<>();

        if (current.getParentFile() != null) {
            entries.add(current.getParentFile());        // ".."
        }
        File[] children = current.listFiles();
        if (children != null) {
            Arrays.sort(children, new Comparator<File>() {
                @Override
                public int compare(File a, File b) {
                    if (a.isDirectory() && !b.isDirectory()) return -1;
                    if (!a.isDirectory() && b.isDirectory()) return 1;
                    return a.getName().compareToIgnoreCase(b.getName());
                }
            });
            for (File child : children) {
                if (child.isHidden()) continue;
                if (child.isDirectory() || filter.accept(child)) {
                    entries.add(child);
                }
            }
        }

        final String[] labels = new String[entries.size() + (folderMode ? 1 : 0)];
        int offset = 0;
        if (folderMode) {
            labels[0] = "[ use this folder ]";
            offset = 1;
        }
        for (int i = 0; i < entries.size(); i++) {
            File f = entries.get(i);
            String prefix = f.isDirectory() ? "[dir] " : "";
            labels[i + offset] = prefix + f.getName();
        }

        if (labels.length == 0) {
            showMessage(activity, "Nothing here. Use the phone's file manager to copy"
                    + " music into " + current.getAbsolutePath());
            return;
        }

        new AlertDialog.Builder(activity)
                .setTitle(title + " — " + current.getAbsolutePath())
                .setItems(labels, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        if (folderMode && which == 0) {
                            callback.onFile(current);
                            return;
                        }
                        File picked = entries.get(which - (folderMode ? 1 : 0));
                        if (picked.isDirectory()) {
                            browse(activity, picked, title, filter, callback, folderMode);
                        } else {
                            callback.onFile(picked);
                        }
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private static void showMessage(Activity activity, String message) {
        new AlertDialog.Builder(activity)
                .setMessage(message)
                .setPositiveButton(android.R.string.ok, null)
                .show();
    }
}
