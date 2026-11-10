package com.tongyou.travel.chat

import androidx.compose.foundation.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.*
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tongyou.travel.UrlPolicy
import com.tongyou.travel.data.TravelApi
import org.commonmark.node.*
import org.commonmark.parser.Parser
import org.commonmark.ext.gfm.tables.*

object MarkdownParser {
    private val parser = Parser.builder().extensions(listOf(TablesExtension.create())).build()
    fun parse(text: String): Node = parser.parse(text)
}
fun Node.children(): List<Node> = generateSequence(firstChild) { it.next }.toList()

@Composable fun Markdown(text: String) {
    val document = remember(text) { MarkdownParser.parse(text) }
    SelectionContainer { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) { document.children().forEach { Block(it) } } }
}

@Composable private fun Block(node: Node, depth: Int = 0) {
    val accent = MaterialTheme.colorScheme.primary
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val links = TextLinkStyles(SpanStyle(color = accent))
    when (node) {
        is Heading -> Text(inline(node, links), style = when (node.level) {
            1 -> MaterialTheme.typography.headlineSmall; 2 -> MaterialTheme.typography.titleLarge; else -> MaterialTheme.typography.titleMedium
        }, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = if (node.level <= 2) 8.dp else 2.dp))
        is org.commonmark.node.Paragraph -> {
            val images = descendants(node).filterIsInstance<Image>()
            val prose = inline(node, links)
            if (prose.isNotBlank()) Text(prose, style = MaterialTheme.typography.bodyLarge)
            images.forEach { picture ->
                TravelApi.media(picture.destination)?.let { url ->
                    AsyncImage(url, picture.children().filterIsInstance<Text>().joinToString("") { it.literal },
                        Modifier.fillMaxWidth().height(200.dp).clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                        contentScale = ContentScale.Crop)
                }
            }
        }
        is BulletList, is OrderedList -> Column(Modifier.padding(start = (depth.coerceAtMost(3) * 12).dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            node.children().forEachIndexed { index, child ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (node is OrderedList) Text("${node.markerStartNumber + index}.", color = accent, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                    else Box(Modifier.padding(top = 10.dp).size(5.dp).clip(CircleShape).background(accent.copy(alpha = .7f)))
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) { child.children().forEach { Block(it, depth + 1) } }
                }
            }
        }
        is BlockQuote -> Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(Modifier.width(3.dp).fillMaxHeight().clip(RoundedCornerShape(2.dp)).background(accent.copy(alpha = .5f)))
            CompositionLocalProvider(LocalContentColor provides muted) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) { node.children().forEach { Block(it, depth) } }
            }
        }
        is FencedCodeBlock -> CodeBlock(node.literal)
        is IndentedCodeBlock -> CodeBlock(node.literal)
        is ThematicBreak -> HorizontalDivider(Modifier.padding(vertical = 4.dp), color = MaterialTheme.colorScheme.outlineVariant)
        is TableBlock -> {
            // Fixed-width columns in a horizontal scroll, inside a rounded hairline card (same as iOS).
            val rows = node.children().flatMap { it.children() }
            val shape = RoundedCornerShape(16.dp)
            Column(Modifier.clip(shape).border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape)
                .background(MaterialTheme.colorScheme.surface.copy(alpha = .9f)).horizontalScroll(rememberScrollState())) {
                rows.forEachIndexed { index, row ->
                    Row(Modifier.background(if (index == 0) accent.copy(alpha = .07f) else Color.Transparent)) {
                        row.children().forEach { cell ->
                            Text(inline(cell, links), Modifier.width(180.dp).padding(horizontal = 12.dp, vertical = 10.dp),
                                style = MaterialTheme.typography.bodyMedium, fontWeight = if (index == 0) FontWeight.SemiBold else FontWeight.Normal)
                        }
                    }
                    if (index < rows.lastIndex) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            }
        }
        is HtmlBlock -> Text(node.literal) // Render untrusted HTML as inert text.
        else -> node.children().forEach { Block(it, depth) }
    }
}
private fun descendants(node: Node): List<Node> = node.children().flatMap { listOf(it) + descendants(it) }

@Composable private fun CodeBlock(value: String) {
    Text(value.trimEnd(), Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceVariant)
        .horizontalScroll(rememberScrollState()).padding(12.dp), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
}

private fun inline(node: Node, links: TextLinkStyles = TextLinkStyles(SpanStyle(color = Color(0xFF2563EB)))): AnnotatedString = buildAnnotatedString {
    fun add(current: Node) {
        when (current) {
            is Text -> append(current.literal)
            is SoftLineBreak -> append(' ')
            is HardLineBreak -> append('\n')
            is Code -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Color(0x22888888))) { append(current.literal) }
            is StrongEmphasis -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { current.children().forEach(::add) }
            is Emphasis -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { current.children().forEach(::add) }
            is Link -> {
                if (UrlPolicy.external(current.destination)) withLink(LinkAnnotation.Url(current.destination, links)) { current.children().forEach(::add) }
                else current.children().forEach(::add)
            }
            is Image -> Unit
            is HtmlInline -> append(current.literal)
            else -> current.children().forEach(::add)
        }
    }
    add(node)
}
