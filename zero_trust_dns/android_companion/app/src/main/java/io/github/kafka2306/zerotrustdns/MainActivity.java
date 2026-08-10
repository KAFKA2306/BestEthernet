package io.github.kafka2306.zerotrustdns;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String TAILSCALE_PACKAGE = "com.tailscale.ipn";
    private static final String CANARY = "ready.zerotrustdns.test";
    private static final Uri TAILSCALE_PLAY = Uri.parse("market://details?id=" + TAILSCALE_PACKAGE);
    private static final Uri TAILSCALE_WEB = Uri.parse("https://tailscale.com/download/android");
    private static final Uri TAILSCALE_DNS_ADMIN = Uri.parse("https://login.tailscale.com/admin/dns");

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private TextView status;
    private TextView detail;
    private Button primary;
    private State state = State.CHECKING;

    private enum State {
        CHECKING,
        NEED_TAILSCALE,
        NEED_VPN,
        NEED_DNS_ADMIN,
        READY,
        ERROR
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
        primary.setOnClickListener(v -> performPrimaryAction());
    }

    @Override
    protected void onResume() {
        super.onResume();
        verifyState();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private View buildUi() {
        int pad = dp(24);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView title = new TextView(this);
        title.setText("ZeroTrustDNS");
        title.setTextSize(30f);
        title.setTextColor(Color.rgb(13, 48, 99));
        title.setGravity(Gravity.CENTER);
        root.addView(title, matchWrap());

        TextView subtitle = new TextView(this);
        subtitle.setText("Androidを、認証済みのプライベートDNSへ接続します。\nこのアプリ自身はVPN通信を読み取りません。");
        subtitle.setTextSize(16f);
        subtitle.setGravity(Gravity.CENTER);
        subtitle.setPadding(0, dp(12), 0, dp(28));
        root.addView(subtitle, matchWrap());

        status = new TextView(this);
        status.setText("確認中…");
        status.setTextSize(22f);
        status.setGravity(Gravity.CENTER);
        status.setPadding(dp(16), dp(18), dp(16), dp(12));
        root.addView(status, matchWrap());

        detail = new TextView(this);
        detail.setTextSize(15f);
        detail.setGravity(Gravity.CENTER);
        detail.setPadding(dp(8), 0, dp(8), dp(24));
        root.addView(detail, matchWrap());

        primary = new Button(this);
        primary.setText("セットアップを完了");
        primary.setTextSize(18f);
        LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(56));
        buttonParams.setMargins(0, dp(8), 0, 0);
        root.addView(primary, buttonParams);

        TextView safety = new TextView(this);
        safety.setText("必要権限: ネットワーク状態の確認のみ\nVPN権限・Accessibility・root権限は要求しません");
        safety.setTextSize(13f);
        safety.setTextColor(Color.DKGRAY);
        safety.setGravity(Gravity.CENTER);
        safety.setPadding(0, dp(28), 0, 0);
        root.addView(safety, matchWrap());

        return root;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void verifyState() {
        setUi(State.CHECKING, "確認中…", "Tailscale・VPN・ZeroTrustDNS経路を確認しています。", "確認中…");

        if (!isTailscaleInstalled()) {
            setUi(State.NEED_TAILSCALE,
                    "Tailscaleが必要です",
                    "通信本体にはTailscale公式Androidクライアントを使用します。",
                    "Tailscaleをインストール");
            return;
        }

        if (!isVpnActive()) {
            setUi(State.NEED_VPN,
                    "Tailscale接続が必要です",
                    "Tailscaleを開いて、このZeroTrustDNSサーバーと同じtailnetへ接続してください。AndroidのVPN確認はOSが表示します。",
                    "Tailscaleを開く");
            return;
        }

        executor.execute(() -> {
            try {
                InetAddress[] answers = InetAddress.getAllByName(CANARY);
                Inet4Address matched = null;
                for (InetAddress answer : answers) {
                    if (answer instanceof Inet4Address && isTailscaleAddress(answer.getAddress())) {
                        matched = (Inet4Address) answer;
                        break;
                    }
                }
                Inet4Address finalMatched = matched;
                runOnUiThread(() -> {
                    if (finalMatched != null) {
                        setUi(State.READY,
                                "保護は有効です",
                                "VPN接続済み / ZeroTrustDNS canary一致: " + finalMatched.getHostAddress(),
                                "もう一度確認");
                    } else {
                        setUi(State.NEED_DNS_ADMIN,
                                "DNS適用が残っています",
                                "VPNは有効ですが " + CANARY + " がZeroTrustDNSへ到達していません。tailnetのGlobal nameserverとOverride DNS serversを確認します。",
                                "Tailscale DNS設定を開く");
                    }
                });
            } catch (Exception e) {
                runOnUiThread(() -> setUi(State.NEED_DNS_ADMIN,
                        "DNS適用が残っています",
                        "VPNは有効ですがZeroTrustDNS canaryを解決できません。",
                        "Tailscale DNS設定を開く"));
            }
        });
    }

    private boolean isTailscaleInstalled() {
        return getPackageManager().getLaunchIntentForPackage(TAILSCALE_PACKAGE) != null;
    }

    private boolean isVpnActive() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        for (Network network : cm.getAllNetworks()) {
            NetworkCapabilities caps = cm.getNetworkCapabilities(network);
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                return true;
            }
        }
        return false;
    }

    private static boolean isTailscaleAddress(byte[] raw) {
        if (raw == null || raw.length != 4) return false;
        int first = raw[0] & 0xff;
        int second = raw[1] & 0xff;
        return first == 100 && second >= 64 && second <= 127;
    }

    private void performPrimaryAction() {
        switch (state) {
            case NEED_TAILSCALE:
                openTailscaleInstall();
                break;
            case NEED_VPN:
                Intent launch = getPackageManager().getLaunchIntentForPackage(TAILSCALE_PACKAGE);
                if (launch != null) startActivity(launch);
                else openTailscaleInstall();
                break;
            case NEED_DNS_ADMIN:
                startActivity(new Intent(Intent.ACTION_VIEW, TAILSCALE_DNS_ADMIN));
                break;
            case READY:
            case ERROR:
            case CHECKING:
            default:
                verifyState();
                break;
        }
    }

    private void openTailscaleInstall() {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, TAILSCALE_PLAY));
        } catch (ActivityNotFoundException e) {
            startActivity(new Intent(Intent.ACTION_VIEW, TAILSCALE_WEB));
        }
    }

    private void setUi(State newState, String headline, String explanation, String buttonText) {
        state = newState;
        status.setText(headline);
        detail.setText(explanation);
        primary.setText(buttonText);
        primary.setEnabled(newState != State.CHECKING);
        if (newState == State.READY) {
            status.setTextColor(Color.rgb(16, 122, 63));
        } else if (newState == State.ERROR) {
            status.setTextColor(Color.rgb(180, 35, 35));
        } else {
            status.setTextColor(Color.rgb(13, 48, 99));
        }
    }
}
