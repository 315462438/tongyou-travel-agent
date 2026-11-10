package com.tongyou.travel.ui

import android.animation.ValueAnimator
import android.os.Build
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.chrisbanes.haze.*

/** #2563EB — the same brand blue as the web and iOS clients. */
val BrandBlue = Color(0xFF2563EB)
val LocalMotion = staticCompositionLocalOf { true }
/** Space the floating bottom bar covers; scrolling content pads by this so it can pass *under* the glass. */
val LocalBottomInset = compositionLocalOf { 0.dp }

// Every container role is set explicitly: Material 3's defaults are purple-tinted, which is where the
// lavender cards and buttons came from.
private val Light = lightColorScheme(
    primary = BrandBlue, onPrimary = Color.White, primaryContainer = Color(0xFFE3ECFE), onPrimaryContainer = Color(0xFF12306F),
    secondary = Color(0xFF4B5B76), onSecondary = Color.White, secondaryContainer = Color(0xFFE8EEFB), onSecondaryContainer = Color(0xFF202A39),
    tertiary = Color(0xFFD9691F), onTertiary = Color.White, tertiaryContainer = Color(0xFFFFEBDD), onTertiaryContainer = Color(0xFF5A2A08),
    background = Color(0xFFF3F6FC), onBackground = Color(0xFF202A39), surface = Color.White, onSurface = Color(0xFF202A39),
    surfaceVariant = Color(0xFFEDF1F8), onSurfaceVariant = Color(0xFF6D7889), outline = Color(0xFFB8C3D4), outlineVariant = Color(0xFFDDE4EF),
    surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFF8FAFD), surfaceContainer = Color(0xFFF3F6FC),
    surfaceContainerHigh = Color(0xFFEDF1F8), surfaceContainerHighest = Color(0xFFE6EBF4), surfaceTint = Color.Transparent,
)
private val Dark = darkColorScheme(
    primary = Color(0xFF8FB0FF), onPrimary = Color(0xFF0B1F4D), primaryContainer = Color(0xFF1D3470), onPrimaryContainer = Color(0xFFDCE6FF),
    secondary = Color(0xFFB4C0D6), onSecondary = Color(0xFF1C2637), secondaryContainer = Color(0xFF232C3F), onSecondaryContainer = Color(0xFFE4E9F3),
    tertiary = Color(0xFFFFB68A), onTertiary = Color(0xFF4A2105), tertiaryContainer = Color(0xFF3B2A1E), onTertiaryContainer = Color(0xFFFFDCC6),
    background = Color(0xFF0D111B), onBackground = Color(0xFFE8ECF4), surface = Color(0xFF161C29), onSurface = Color(0xFFE8ECF4),
    surfaceVariant = Color(0xFF222A3A), onSurfaceVariant = Color(0xFF9AA6BA), outline = Color(0xFF4A5568), outlineVariant = Color(0xFF2A3345),
    surfaceContainerLowest = Color(0xFF0B0F18), surfaceContainerLow = Color(0xFF131926), surfaceContainer = Color(0xFF161C29),
    surfaceContainerHigh = Color(0xFF1D2433), surfaceContainerHighest = Color(0xFF252D3E), surfaceTint = Color.Transparent,
)

@Composable fun TongyouTheme(content: @Composable () -> Unit) {
    val base = Typography()
    // Chinese text needs smaller display sizes and firmer weights than Material's Latin-tuned defaults.
    // One notch below Material's Latin-tuned defaults: Chinese glyphs are visually larger at the same sp,
    // and the old sizes read as oversized on device (real-phone screenshot, 2026-11-10).
    val type = base.copy(
        displaySmall = base.displaySmall.copy(fontSize = 26.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold),
        headlineLarge = base.headlineLarge.copy(fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold),
        headlineMedium = base.headlineMedium.copy(fontSize = 22.sp, lineHeight = 30.sp, fontWeight = FontWeight.SemiBold),
        headlineSmall = base.headlineSmall.copy(fontSize = 19.sp, lineHeight = 27.sp, fontWeight = FontWeight.SemiBold),
        titleLarge = base.titleLarge.copy(fontSize = 17.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontSize = 15.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
        titleSmall = base.titleSmall.copy(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium),
        bodyLarge = base.bodyLarge.copy(fontSize = 15.sp, lineHeight = 24.sp),
        bodyMedium = base.bodyMedium.copy(fontSize = 14.sp, lineHeight = 21.sp),
        bodySmall = base.bodySmall.copy(fontSize = 12.sp, lineHeight = 18.sp),
        labelLarge = base.labelLarge.copy(fontSize = 13.sp, lineHeight = 18.sp),
        labelMedium = base.labelMedium.copy(fontSize = 12.sp, lineHeight = 16.sp),
        labelSmall = base.labelSmall.copy(fontSize = 11.sp, lineHeight = 15.sp),
    )
    CompositionLocalProvider(LocalMotion provides ValueAnimator.areAnimatorsEnabled()) {
        MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, typography = type, content = content)
    }
}

/** The soft blue wash behind every screen (same idea as the web client's page background). */
@Composable fun Backdrop(modifier: Modifier = Modifier, content: @Composable BoxScope.() -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Box(modifier.background(scheme.background)
        .background(Brush.radialGradient(listOf(scheme.primary.copy(alpha = .16f), Color.Transparent), center = Offset(0f, 0f), radius = 1100f)), content = content)
}

/** Real backdrop blur needs Android 12+; below that (or with animations off) fall back to a near-opaque tint. */
@Composable fun glassAvailable() = Build.VERSION.SDK_INT >= 31 && LocalMotion.current

/** A bar that shows the page scrolling behind it. `source` must be the HazeState attached to that page. */
@Composable fun Modifier.glassBar(source: HazeState): Modifier {
    val tint = MaterialTheme.colorScheme.surface
    // A strong tint: a light one let photos bleed through as muddy colour blotches.
    return if (glassAvailable()) hazeEffect(source) { backgroundColor = tint; tints = listOf(HazeTint(tint.copy(alpha = .82f))); blurRadius = 28.dp; noiseFactor = 0f }
    else background(tint.copy(alpha = .97f))
}

/** A quiet white card with a hairline border — the surface used across the product. */
@Composable fun GlassCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val shape = RoundedCornerShape(24.dp)
    Column(modifier.clip(shape).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f), shape)
        .border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
}

@Composable fun ErrorNotice(message: String, retry: (() -> Unit)? = null) {
    Surface(color = MaterialTheme.colorScheme.errorContainer, shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text(message, color = MaterialTheme.colorScheme.onErrorContainer, style = MaterialTheme.typography.bodyMedium)
            if (retry != null) TextButton(onClick = retry) { Text("重试") }
        }
    }
}

/**
 * iOS-style sheet with the same parameters as AlertDialog, so forms switch over without rewriting:
 * slides up from the bottom, cancel on the left, title in the middle, the confirm action on the right.
 * Short yes/no confirmations stay as AlertDialog (iOS uses alerts for those too).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SheetDialog(onDismissRequest: () -> Unit, confirmButton: @Composable () -> Unit, modifier: Modifier = Modifier,
                            dismissButton: (@Composable () -> Unit)? = null, title: (@Composable () -> Unit)? = null, text: (@Composable () -> Unit)? = null) {
    ModalBottomSheet(onDismissRequest, modifier, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = MaterialTheme.colorScheme.background, shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
        dragHandle = { BottomSheetDefaults.DragHandle(color = MaterialTheme.colorScheme.outline) }) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(bottom = 16.dp)) {
            Box(Modifier.fillMaxWidth().padding(horizontal = 8.dp).heightIn(min = 48.dp), contentAlignment = Alignment.Center) {
                Box(Modifier.align(Alignment.CenterStart)) { dismissButton?.invoke() }
                ProvideTextStyle(MaterialTheme.typography.titleMedium) { title?.invoke() }
                Box(Modifier.align(Alignment.CenterEnd)) {
                    // Confirm reads as the primary action, like the bold right-hand button on iOS.
                    ProvideTextStyle(MaterialTheme.typography.titleMedium) { confirmButton() }
                }
            }
            Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp)) { text?.invoke() }
        }
    }
}
