package com.tongyou.travel

import com.tongyou.travel.chat.*
import com.tongyou.travel.data.wireJson
import kotlinx.serialization.decodeFromString
import org.commonmark.ext.gfm.tables.TableBlock
import org.commonmark.node.*
import org.junit.Test
import org.junit.Assert.*

class MarkdownTest {
    @Test fun parsesTheGuideStructuresNativelyIncludingGfmTables() {
        val document = MarkdownParser.parse("# 旅行\n\n> 提示\n\n- 景点\n- 美食\n\n| 地点 | 时间 |\n| --- | --- |\n| 西湖 | 09:00 |\n\n![西湖](/api/uploads/abc)\n\n```text\n地铁 1 号\n```\n")
        val blocks = document.children()
        assertTrue(blocks.any { it is Heading }); assertTrue(blocks.any { it is BlockQuote }); assertTrue(blocks.any { it is BulletList })
        assertTrue(blocks.any { it is TableBlock }); assertTrue(blocks.any { it is FencedCodeBlock })
        assertTrue(blocks.any { it.children().any { child -> child is Image } })
    }
    @Test fun toleratesPartialStreamingMarkdownAndMissingOptionalFields() {
        for (value in listOf("## Day", "**还在生成", "[链接](https://", "|地点|")) assertNotNull(MarkdownParser.parse(value))
        val reply = wireJson.decodeFromString<MessagesReply>("""{"messages":[{"id":"x","role":"assistant","content":null,"meta":{"streaming":true,"unknown":1}}],"running":true,"new_field":42}""")
        assertTrue(reply.messages.first().streaming); assertEquals("", reply.messages.first().content)
    }
}
